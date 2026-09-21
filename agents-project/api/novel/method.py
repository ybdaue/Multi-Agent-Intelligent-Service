"""小说的查询口：书架、正文、各类设定、这一章的台账、这本书的改动清单，外加改名 / 删书 / 改章状态三笔写。

除了末尾那三个写口（改名、删书、改章状态），其余全部只读。userId 一律从 request.state.user_id 取
（auth 中间件按 Bearer token 解析出来的 better-auth cuid），再核这本书确实挂在这个用户名下 ——
前端传进来的 id 只是定位，不作鉴权凭据。所以每个口子都先过 _require_novel，别人的书一律当
"不存在"（404），不给"有没有"这个信息。写口同理：UPDATE / DELETE 都带 userId 限定，
影响 0 行就是 404，改不到也删不掉别人的书。

为什么只建书没有别的写口：建书那一整套（书名、套路、风格、主角、核心设定）走
api/novel/setup.py 的开书图，由模型照着 skill 逐项问齐、用户过目后落库，不经 HTTP 表单。
书 id 由「新建小说」弹窗打开时就生成好，不需要后端先建一行占位。

参数为什么叫 threadId：一个 thread 就是一本小说（见 api/novel/agent.py），前端手上只有会话的
threadId，所以入口认这个名字；库里存的是 novelId，两个值本来就是同一个。

一个接口对应前端一个按钮：/novels 是侧栏书架，其余是工作区各标签页（正文 / 大纲 / 角色 /
世界观 / 世界线 / 势力阵营 / 编年史 / 物品 / 关系 / 灵感 / 受影响点）。返回的键直接用库里的
列名，前端按各自的标签页渲染，不在这里做人话转换 —— 只有台账与受影响点做了，因为那两处
前端要的是"这条叫什么、这是什么类型"。

台账（novel_chapter_ref）为什么由前端来读：writer 写完就把"这一章用到 / 新造了什么"报进了这张表，
它是影响分析的底账 —— 改设定时"哪些章会受波及"正是反查它算出来的。前端要展示只能走这里，
没有别的口子。
"""
from fastapi import APIRouter, Form, HTTPException, Query, Request

from agents.novel.utils.ledger import CATALOG, TYPE_LABEL
from api.utils.db import pg_pool

router = APIRouter(prefix="/api/novel/method", tags=["小说服务"])

# refType → (表名, 认得出这条叫什么的那一列)。照 ledger 的 CATALOG 来，不另立一份 ——
# 目录、台账、档案三处认的是同一套表与列名，各自发明迟早对不上。
_NAME_COLUMN = {ref_type: (table, label) for ref_type, table, label in CATALOG}

# 戏份说成人话。取值来自 ledger.ROLE_VALUES，前端展示用；认不出就原样给出去。
_ROLE_LABELS = {"key": "关键戏份", "state": "交代状态", "mention": "提及"}

# ImpactTarget 的取值说成人话。它比 RefType 多出 novel / chapter / state / relation 四项，
# 所以是在 TYPE_LABEL 上补齐，不是另起一套。
_IMPACT_LABELS = {
    **TYPE_LABEL,
    "novel": "小说",
    "chapter": "章节",
    "state": "章节状态",
    "relation": "人物关系",
}


def _label(kind: str) -> str:
    return _IMPACT_LABELS.get(kind, kind)


# novel_chapter.status 的三档，与前端 types.ts 的 ChapterStatus 一一对应：
# done 完成 / draft 草稿 / fixing 待修复。库里是普通字符串列，没有约束，所以在这里挡一道 ——
# 别让前端一个手滑把状态写成第四种，之后没人认得出它。
CHAPTER_STATUSES = ("done", "draft", "fixing")


async def _own_novel(conn, novel_id: str, user_id: str) -> bool:
    """这本书是不是这个用户的。不是就当"不存在"处理 —— 别让接口能探出别人有哪些书。"""
    cur = await conn.execute(
        'SELECT 1 FROM novel WHERE id = %s AND "userId" = %s', (novel_id, user_id)
    )
    return await cur.fetchone() is not None


async def _require_novel(conn, novel_id: str, user_id: str) -> None:
    """每个口子的第一道闸：不是自己的书就 404，后面的查询一条也不发。"""
    if not await _own_novel(conn, novel_id, user_id):
        raise HTTPException(status_code=404, detail="小说不存在")


# 各设定表要出的列（库里的列名，也是返回体的键）。逐表列清楚，不 SELECT *：
# 表结构加了列不会莫名其妙地漏到前端去。
_COLUMNS: dict[str, tuple[str, ...]] = {
    "novel_outline": ("id", "content", "status", "startChapterId", "endChapterId", "order"),
    "novel_character": ("id", "name", "sex", "age", "birthYear", "deathYear", "description",
                        "identity", "personality", "ability", "role"),
    "novel_world_rule": ("id", "name", "rule", "status", "startChapterId", "endChapterId"),
    "novel_timeline": ("id", "title", "status", "year", "description",
                       "startChapterId", "endChapterId"),
    "novel_faction": ("id", "name", "type", "location", "description", "stance"),
    "novel_chronicle": ("id", "title", "year", "content"),
    "novel_item": ("id", "name", "type", "description", "firstAppearanceChapterId",
                   "status", "ownerId"),
    "novel_relation": ("id", "fromCharId", "toCharId", "relationType", "strength",
                       "description", "startChapterId", "endChapterId", "status"),
    "novel_inspiration": ("id", "type", "content", "usedChapterIds"),
}


async def _rows(conn, table: str, novel_id: str, order_by: str) -> list[dict]:
    """按 _COLUMNS 声明的列取这本书的某一类设定，键就是列名。

    表名、列名、排序都取自本模块的常量，没有一个字来自请求，所以这里的拼接安全；
    随请求变的值（novel_id）一律走 %s。
    """
    columns = _COLUMNS[table]
    cols = ", ".join(f'"{col}"' for col in columns)
    cur = await conn.execute(
        f'SELECT {cols} FROM {table} WHERE "novelId" = %s ORDER BY {order_by}',
        (novel_id,),
    )
    return [dict(zip(columns, row)) for row in await cur.fetchall()]


async def _char_names(conn, novel_id: str) -> dict[str, str]:
    """人物 id → 姓名。关系图、物品持有者这些地方给前端看的是人名，不是 cuid。"""
    cur = await conn.execute(
        'SELECT id, name FROM novel_character WHERE "novelId" = %s', (novel_id,)
    )
    return {row[0]: row[1] for row in await cur.fetchall()}


async def _ref_names(conn, novel_id: str, refs: list[tuple]) -> dict[tuple[str, str], str]:
    """把 refId 换成"这条叫什么"，给前端展示用。

    目标可能是九类里的任何一类，认名字的列各不相同（人物认 name、大纲认 content 的头 40 字，
    见 ledger.CATALOG），所以按类型分批发：每类一条 SQL，一次把该类要用的 id 全查回来。
    查不到的（行被删了、id 是模型编的）就不出现在结果里，对应那一条的名字留空。
    """
    wanted: dict[str, list[str]] = {}
    for ref_type, ref_id, _role in refs:
        wanted.setdefault(ref_type, []).append(ref_id)

    names: dict[tuple[str, str], str] = {}
    for ref_type, ref_ids in wanted.items():
        found = _NAME_COLUMN.get(ref_type)
        if found is None:
            continue
        table, label = found
        cur = await conn.execute(
            f'SELECT id, {label} FROM {table} WHERE "novelId" = %s AND id = ANY(%s)',
            (novel_id, ref_ids),
        )
        for ref_id, name in await cur.fetchall():
            names[(ref_type, ref_id)] = " ".join(str(name or "").split())
    return names


@router.get("/novels")
async def list_novels(request: Request):
    """这个用户的书架：每本书带上它的章节列表，侧栏与章节列表一次拿全。

    章节只出列表要用的几列，正文由 /chapter/content 单取 —— 列表里带上全文，一本书几十章
    就是白白搬几百 KB。threadId（也就是 novelId）前端就是从这里拿的。
    """
    user_id = request.state.user_id
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT id, title, "wordCount", tropes, style, "updatedAt" FROM novel '
            'WHERE "userId" = %s ORDER BY "updatedAt" DESC',
            (user_id,),
        )
        novels = await cur.fetchall()
        if not novels:
            return {"total": 0, "novels": []}

        cur = await conn.execute(
            'SELECT id, "novelId", title, "order", status, "wordCount" FROM novel_chapter '
            'WHERE "novelId" = ANY(%s) ORDER BY "novelId", "order", id',
            ([row[0] for row in novels],),
        )
        chapters = await cur.fetchall()

    by_novel: dict[str, list[dict]] = {}
    for chapter_id, novel_id, title, order, status, word_count in chapters:
        by_novel.setdefault(novel_id, []).append({
            "id": chapter_id,
            "title": title or "",
            "order": order,
            "status": status,
            "wordCount": word_count,
        })

    return {
        "total": len(novels),
        "novels": [
            {
                "id": novel_id,
                "title": title or "",
                "wordCount": word_count,
                "tropes": tropes or "",
                "style": style or "",
                "updatedAt": updated_at,
                "chapters": by_novel.get(novel_id, []),
            }
            for novel_id, title, word_count, tropes, style, updated_at in novels
        ],
    }


@router.get("/chapter/content")
async def get_chapter_content(
    request: Request,
    threadId: str = Query(..., description="会话 ID（也就是小说 ID）"),
    chapterId: str = Query(..., description="章节 ID"),
):
    """正文标签页要的：这一章的正文、精简，和前文总结。"""
    async with pg_pool.connection() as conn:
        await _require_novel(conn, threadId, request.state.user_id)

        cur = await conn.execute(
            'SELECT id, title, "order", status, "wordCount", summary, content, "pastSummary" '
            'FROM novel_chapter WHERE id = %s AND "novelId" = %s',
            (chapterId, threadId),
        )
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="章节不存在")

    chapter_id, title, order, status, word_count, summary, content, past_summary = row
    return {
        "threadId": threadId,
        "chapterId": chapter_id,
        "title": title or "",
        "order": order,
        "status": status,
        "wordCount": word_count,
        "summary": summary or "",
        "content": content or "",
        "pastSummary": past_summary or {},
    }


@router.get("/outlines")
async def list_outlines(request: Request, threadId: str):
    """大纲标签页：这本书的每一条大纲，按 order。"""
    async with pg_pool.connection() as conn:
        await _require_novel(conn, threadId, request.state.user_id)
        rows = await _rows(conn, "novel_outline", threadId, '"order", "createdAt", id')
    return {"threadId": threadId, "total": len(rows), "outlines": rows}


@router.get("/characters")
async def list_characters(request: Request, threadId: str):
    """人物档案标签页：主角配角反派都在这一份里，前端按 role 分组。"""
    async with pg_pool.connection() as conn:
        await _require_novel(conn, threadId, request.state.user_id)
        rows = await _rows(conn, "novel_character", threadId, '"role", "createdAt", id')
    return {"threadId": threadId, "total": len(rows), "characters": rows}


@router.get("/world-rules")
async def list_world_rules(request: Request, threadId: str):
    """世界观标签页：规则 / 等级 / 力量体系这一套。"""
    async with pg_pool.connection() as conn:
        await _require_novel(conn, threadId, request.state.user_id)
        rows = await _rows(conn, "novel_world_rule", threadId, '"createdAt", id')
    return {"threadId": threadId, "total": len(rows), "worldRules": rows}


@router.get("/timelines")
async def list_timelines(request: Request, threadId: str):
    """世界线标签页：按年份往前排（年份是字符串，库里没做规范化，就照原样排）。"""
    async with pg_pool.connection() as conn:
        await _require_novel(conn, threadId, request.state.user_id)
        rows = await _rows(conn, "novel_timeline", threadId, '"year", "createdAt", id')
    return {"threadId": threadId, "total": len(rows), "timelines": rows}


@router.get("/factions")
async def list_factions(request: Request, threadId: str):
    """势力阵营标签页。"""
    async with pg_pool.connection() as conn:
        await _require_novel(conn, threadId, request.state.user_id)
        rows = await _rows(conn, "novel_faction", threadId, '"createdAt", id')
    return {"threadId": threadId, "total": len(rows), "factions": rows}


@router.get("/chronicles")
async def list_chronicles(request: Request, threadId: str):
    """编年史标签页：大事记，按年份。"""
    async with pg_pool.connection() as conn:
        await _require_novel(conn, threadId, request.state.user_id)
        rows = await _rows(conn, "novel_chronicle", threadId, '"year", "createdAt", id')
    return {"threadId": threadId, "total": len(rows), "chronicles": rows}


@router.get("/items")
async def list_items(request: Request, threadId: str):
    """物品设定标签页：持有者给的是人名，ownerId 是个 cuid，前端拿着没法显示。"""
    async with pg_pool.connection() as conn:
        await _require_novel(conn, threadId, request.state.user_id)
        rows = await _rows(conn, "novel_item", threadId, '"createdAt", id')
        names = await _char_names(conn, threadId) if rows else {}

    for row in rows:
        row["ownerName"] = names.get(row.get("ownerId") or "", "")
    return {"threadId": threadId, "total": len(rows), "items": rows}


@router.get("/relations")
async def list_relations(request: Request, threadId: str):
    """关系图标签页：两端都补上人名，否则前端只能显示两个 cuid。"""
    async with pg_pool.connection() as conn:
        await _require_novel(conn, threadId, request.state.user_id)
        rows = await _rows(conn, "novel_relation", threadId, '"createdAt", id')
        names = await _char_names(conn, threadId) if rows else {}

    for row in rows:
        row["fromName"] = names.get(row.get("fromCharId") or "", "")
        row["toName"] = names.get(row.get("toCharId") or "", "")
    return {"threadId": threadId, "total": len(rows), "relations": rows}


@router.get("/inspirations")
async def list_inspirations(request: Request, threadId: str):
    """灵感库标签页：跨章的构思，usedChapterIds 是它已经用在哪些章。"""
    async with pg_pool.connection() as conn:
        await _require_novel(conn, threadId, request.state.user_id)
        rows = await _rows(conn, "novel_inspiration", threadId, '"createdAt", id')
    return {"threadId": threadId, "total": len(rows), "inspirations": rows}


@router.get("/chapter/ledger")
async def get_chapter_ledger(
    request: Request,
    threadId: str = Query(..., description="会话 ID（也就是小说 ID）"),
    chapterId: str = Query(..., description="章节 ID"),
):
    """这一章用到、新造了哪些设定：按 novel_chapter_ref 取它挂着的关联，每条补上类型与名字。

    新造的东西在入库时也会挂一条 ref（见 ledger.write_ledger），所以"用到的"和"新造的"都在这一份里，
    不另开一张表给新造的。
    """
    async with pg_pool.connection() as conn:
        await _require_novel(conn, threadId, request.state.user_id)

        cur = await conn.execute(
            'SELECT id, title, "order" FROM novel_chapter WHERE id = %s AND "novelId" = %s',
            (chapterId, threadId),
        )
        chapter = await cur.fetchone()
        if chapter is None:
            raise HTTPException(status_code=404, detail="章节不存在")

        # 入账顺序取：台账是写这一章时一条条报上来的，按时间排最接近正文里的出场顺序。
        cur = await conn.execute(
            'SELECT "refType", "refId", role FROM novel_chapter_ref '
            'WHERE "chapterId" = %s ORDER BY "createdAt", id',
            (chapterId,),
        )
        refs = await cur.fetchall()
        names = await _ref_names(conn, threadId, refs)

    chapter_id, title, order = chapter
    return {
        "threadId": threadId,
        "chapterId": chapter_id,
        "chapterTitle": title or "",
        "chapterOrder": order,
        "total": len(refs),
        "refs": [
            {
                "refType": ref_type,
                "refTypeLabel": TYPE_LABEL.get(ref_type, ref_type),
                "refId": ref_id,
                "name": names.get((ref_type, ref_id), ""),
                "role": role or "",
                "roleLabel": _ROLE_LABELS.get(role or "", role or ""),
            }
            for ref_type, ref_id, role in refs
        ],
    }


@router.get("/impacts")
async def list_impacts(
    request: Request,
    threadId: str = Query(..., description="会话 ID（也就是小说 ID）"),
):
    """这本书全部"可能受影响的地方"，按改动分组（同一次改动共享一个 changeId）。

    行里的 reason 已经是人话，直接摆给用户看；severity 分三档（must_fix / review / info），
    status 是用户处理到哪一步（pending / accepted / skipped / fixed）。
    """
    async with pg_pool.connection() as conn:
        await _require_novel(conn, threadId, request.state.user_id)

        cur = await conn.execute(
            'SELECT id, "changeId", "changeSummary", "sourceType", "sourceId", "oldValue", '
            '"newValue", "targetType", "targetId", "targetChapter", "reasonKind", reason, '
            'severity, status, resolution, "detectedBy", "createdAt" '
            'FROM novel_change_impact WHERE "novelId" = %s '
            'ORDER BY "createdAt" DESC, "changeId", "targetChapter", id',
            (threadId,),
        )
        rows = await cur.fetchall()

    changes: list[dict] = []
    index: dict[str, dict] = {}
    for row in rows:
        (row_id, change_id, summary, source_type, source_id, old_value, new_value,
         target_type, target_id, target_chapter, reason_kind, reason,
         severity, status, resolution, detected_by, created_at) = row

        group = index.get(change_id)
        if group is None:
            # 一次改动写在一笔事务里，同组的表头取哪一行都一样。
            group = {
                "changeId": change_id,
                "changeSummary": summary,
                "sourceType": source_type,
                "sourceTypeLabel": _label(source_type),
                "sourceId": source_id,
                "createdAt": created_at,
                "total": 0,
                "items": [],
            }
            index[change_id] = group
            changes.append(group)

        group["items"].append({
            "id": row_id,
            "targetType": target_type,
            "targetTypeLabel": _label(target_type),
            "targetId": target_id,
            "targetChapter": target_chapter,
            "reasonKind": reason_kind,
            "reason": reason,
            "severity": severity,
            "status": status,
            "resolution": resolution or "",
            "oldValue": old_value or "",
            "newValue": new_value or "",
            "detectedBy": detected_by or "",
        })
        group["total"] += 1

    return {"threadId": threadId, "total": len(rows), "changes": changes}


# ===== 三个写口 =====


@router.post("/chapter/status")
async def set_chapter_status(
    request: Request,
    novelId: str = Form(..., description="小说 ID（也就是 threadId）"),
    chapterId: str = Form(..., description="章节 ID"),
    status: str = Form(..., description="目标状态：done 完成 / draft 草稿 / fixing 待修复"),
):
    """改一章的状态。

    只动 status 与 updatedAt：正文、精简、前文总结、台账一概不碰，所以这里既不重算字数，
    也不用重跑 update 节点 —— 标个状态不该惊动任何一轮生成。
    """
    if status not in CHAPTER_STATUSES:
        raise HTTPException(status_code=400, detail="未知的章节状态")

    async with pg_pool.connection() as conn:
        await _require_novel(conn, novelId, request.state.user_id)

        cur = await conn.execute(
            'UPDATE novel_chapter SET status = %s, "updatedAt" = now() '
            'WHERE id = %s AND "novelId" = %s RETURNING status',
            (status, chapterId, novelId),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"chapterId": chapterId, "status": row[0]}


@router.post("/novel")
async def rename_novel(
    request: Request,
    novelId: str = Form(..., description="小说 ID（也就是 threadId）"),
    title: str = Form(..., description="新书名"),
):
    """改书名。只动 title 与 updatedAt，设定（tropes / style / 人物 / 大纲 / 世界规则）一概不碰。"""
    title = title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="书名不能为空")

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'UPDATE novel SET title = %s, "updatedAt" = now() '
            'WHERE id = %s AND "userId" = %s RETURNING title',
            (title, novelId, request.state.user_id),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {"novelId": novelId, "title": row[0]}


@router.delete("/novel")
async def delete_novel(
    request: Request,
    novelId: str = Query(..., description="小说 ID（也就是 threadId）"),
):
    """删书。

    章节、各类设定、这一章的台账、受影响清单都靠外键 ON DELETE CASCADE 一并没了，不用逐表删
    （唯一例外是 novel_item.ownerId 的 SET NULL，那是可空归属列）。删掉之后这个 thread 的
    checkpoint 还在，但那个 id 再也不会被取用，不影响。
    """
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'DELETE FROM novel WHERE id = %s AND "userId" = %s RETURNING id',
            (novelId, request.state.user_id),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {"novelId": novelId, "deleted": True}
