"""小说的查询口：书架、正文、各类设定、这一章的台账、这本书的改动清单，外加末尾那几笔写
（改正文 / 删章 / 改章名 / 改书名类型文风 / 改章状态 / 删书 / 改受影响点状态）。

除了末尾那几笔写，其余全部只读。userId 一律从 request.state.user_id 取
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
世界观 / 世界线 / 势力阵营 / 编年史 / 物品 / 伏笔 / 关系 / 灵感 / 受影响点）。返回的键直接用库里的
列名，前端按各自的标签页渲染，不在这里做人话转换 —— 只有台账与受影响点做了，因为那两处
前端要的是"这条叫什么、这是什么类型"。

台账（novel_chapter_ref）为什么由前端来读：writer 写完就把"这一章用到 / 新造了什么"报进了这张表，
它是影响分析的底账 —— 改设定时"哪些章会受波及"正是反查它算出来的。前端要展示只能走这里，
没有别的口子。
"""
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from psycopg.errors import DataError

from agents.novel.utils.chapter_information import NOVEL_WORD_COUNT_SQL, count_chapter_words
from agents.novel.utils.inspiration import (
    add_inspirations,
    parse_items,
    reconcile_inspirations,
    translate,
)
from agents.novel.utils.ledger import TYPE_LABEL
from agents.novel.utils.run_state import RUNNING, read_run
from api.utils.db import pg_pool

router = APIRouter(prefix="/api/novel/method", tags=["小说服务"])

# refType → (表名, 认得出这条叫什么的那一列)。表与列照 ledger.CATALOG 来，只是长文本取整列
# 不截断 —— CATALOG 那份是喂给模型的目录，按 40 字截以省预算；台账是给用户看的，截了用户
# 就见不到内容。分类顺序也照 CATALOG，前端据此排分组。
_NAME_COLUMN = {
    "character": ("novel_character", '"name"'),
    "faction": ("novel_faction", '"name"'),
    "item": ("novel_item", '"name"'),
    "world_rule": ("novel_world_rule", '"name"'),
    "timeline": ("novel_timeline", '"title"'),
    "chronicle": ("novel_chronicle", '"title"'),
    "outline": ("novel_outline", '"content"'),
    "foreshadowing": ("novel_foreshadowing", '"description"'),
    "inspiration": ("novel_inspiration", '"content"'),
}

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

# novel_change_impact.status 的四档，对应 prisma 的 ImpactStatus 枚举。库里是枚举列，写别的值
# 会直接被拒，所以在这里先挡一道，好让错误是一句人话而不是一条数据库报错。
IMPACT_STATUSES = ("pending", "accepted", "skipped", "fixed")

# novel_inspiration.category 的内容类型，与前端 types.ts 的 INSPIRATION_CATEGORY_OPTIONS 一一对应
# （照 CHAPTER_STATUSES 的做法，前后端各留一份常量）。库里是 text[] 数组列，没约束，所以在这里挡一道。
INSPIRATION_CATEGORIES = (
    "style", "plot", "character", "meme", "setting",
    "scene", "dialogue", "imagery", "emotion", "technique", "other",
)

# 使用策略（必用 / 选用 / 不用）是普通字符串列，在这里挡一道白名单。生命周期（复用 / 单次）固定、
# 由分类自动定（见 inspiration.py 的 default_lifecycle），用户改不了，所以没有对应的入参白名单。
INSPIRATION_USAGE = ("must", "selectable", "never")


def _clean_categories(raw: list[str]) -> list[str]:
    """把前端传来的类型过一遍白名单：认不出的丢掉，一个都不剩就退回 other（对应列默认值）。"""
    known = [c for c in raw if c in INSPIRATION_CATEGORIES]
    return list(dict.fromkeys(known)) or ["other"]


def _clean_usage(raw: str) -> str:
    """使用策略过白名单：认不出就退回 selectable。"""
    return raw if raw in INSPIRATION_USAGE else "selectable"


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
    "novel_outline": ("id", "level", "content", "status", "parentId", "startChapterId",
                      "endChapterId", "order"),
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
    "novel_foreshadowing": ("id", "description", "status", "plantedChapterId",
                            "resolvedChapterId"),
    "novel_inspiration": ("id", "sourceId", "title", "category", "type", "content", "usage",
                          "lifecycle", "scenario", "digest", "usedChapterIds"),
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


async def _chapter_names(conn, novel_id: str) -> dict[str, str]:
    """章节 id → "第N章 标题"。伏笔的埋设 / 回收章节要给人看，给个 cuid 前端没法显示。"""
    cur = await conn.execute(
        'SELECT id, "order", title FROM novel_chapter WHERE "novelId" = %s', (novel_id,)
    )
    return {
        row[0]: (f"第{row[1]}章 {row[2]}".strip() if row[2] else f"第{row[1]}章")
        for row in await cur.fetchall()
    }


async def _ref_names(conn, novel_id: str, refs: list[tuple]) -> dict[tuple[str, str], str]:
    """把 refId 换成"这条叫什么"，给前端展示用。

    目标可能是九类里的任何一类，认名字的列各不相同（人物认 name、大纲认 content 整段）——
    见 _NAME_COLUMN。所以按类型分批发：每类一条 SQL，一次把该类要用的 id 全查回来。
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
            names[(ref_type, ref_id)] = str(name or "").strip()
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
            'SELECT id, title, "wordCount", tropes, style, "reviewEnabled", "updatedAt" FROM novel '
            'WHERE "userId" = %s ORDER BY "updatedAt" DESC',
            (user_id,),
        )
        novels = await cur.fetchall()
        if not novels:
            return {"total": 0, "novels": []}

        cur = await conn.execute(
            'SELECT id, "novelId", title, "order", status, "wordCount", "updatedAt" '
            'FROM novel_chapter WHERE "novelId" = ANY(%s) ORDER BY "novelId", "order", id',
            ([row[0] for row in novels],),
        )
        chapters = await cur.fetchall()

    by_novel: dict[str, list[dict]] = {}
    for chapter_id, novel_id, title, order, status, word_count, updated_at in chapters:
        by_novel.setdefault(novel_id, []).append({
            "id": chapter_id,
            "title": title or "",
            "order": order,
            "status": status,
            "wordCount": word_count,
            # 手改正文要带回来的版本令牌，原样给前端（它不许拿去 new Date，微秒会掉）。
            "version": updated_at,
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
                "reviewEnabled": True if review_enabled is None else bool(review_enabled),
                "updatedAt": updated_at,
                "chapters": by_novel.get(novel_id, []),
            }
            for novel_id, title, word_count, tropes, style, review_enabled, updated_at in novels
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
            'SELECT id, title, "order", status, "wordCount", summary, content, "pastSummary", '
            '"updatedAt" FROM novel_chapter WHERE id = %s AND "novelId" = %s',
            (chapterId, threadId),
        )
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="章节不存在")

    (chapter_id, title, order, status, word_count, summary, content, past_summary,
     updated_at) = row
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
        # 版本令牌，见 list_novels 里那句说明。
        "version": updated_at,
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


@router.get("/foreshadowings")
async def list_foreshadowings(request: Request, threadId: str):
    """伏笔标签页：埋设 / 回收章节给的是章名，plantedChapterId / resolvedChapterId 是个 cuid。

    这两列落的是 novel_chapter.id，前端拿着没法显示，所以照 "第N章 标题" 补一份再给出去。
    """
    async with pg_pool.connection() as conn:
        await _require_novel(conn, threadId, request.state.user_id)
        rows = await _rows(conn, "novel_foreshadowing", threadId, '"createdAt", id')
        chapters = await _chapter_names(conn, threadId) if rows else {}

    for row in rows:
        row["plantedChapter"] = chapters.get(row.get("plantedChapterId") or "", "")
        row["resolvedChapter"] = chapters.get(row.get("resolvedChapterId") or "", "")
    return {"threadId": threadId, "total": len(rows), "foreshadowings": rows}


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


# ===== 写口 =====


@router.post("/impact/status")
async def set_impact_status(
    request: Request,
    novelId: str = Form(..., description="小说 ID（也就是 threadId）"),
    impactId: str = Form(..., description="受影响点的行 id"),
    status: str = Form(..., description="处理到哪一步：accepted 接受 / skipped 跳过 / fixed 已修"),
    resolution: str | None = Form(None, description="一句处理说明，不传就不动原来那句"),
):
    """把一处受影响点标成已处理（接受 / 跳过 / 已修），可顺带回填一句处理说明。"""
    if status not in IMPACT_STATUSES:
        raise HTTPException(status_code=400, detail="未知的处理状态")

    async with pg_pool.connection() as conn:
        await _require_novel(conn, novelId, request.state.user_id)

        cur = await conn.execute(
            'UPDATE novel_change_impact '
            'SET status = %s, resolution = COALESCE(%s, resolution), "updatedAt" = now() '
            'WHERE id = %s AND "novelId" = %s RETURNING id, status, resolution',
            (status, resolution, impactId, novelId),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="受影响点不存在")
    return {"id": row[0], "status": row[1], "resolution": row[2] or ""}


@router.post("/chapter/content")
async def save_chapter_content(
    request: Request,
    novelId: str = Form(..., description="小说 ID（也就是 threadId）"),
    chapterId: str = Form(..., description="章节 ID"),
    content: str = Form(..., description="改过的正文"),
    clientUpdatedAt: str = Form(..., description="客户端手上那一版的 updatedAt，原样回传"),
):
    """手改正文落库，同事务里重算这一章与全书字数。

    AI 正在写同一章时挡下来（409）：那一刻库里的真相还没定，谁覆盖谁都不对，交给用户
    等它写完确认、或先停止生成。判据是这一轮的 run marker，不是"这本书在跑" ——
    续写新章时用户手改手上开着的那一章是合法的。

    另有一道版本闸（412，与上面那道 409 分开才分得清）：clientUpdatedAt 跟库里对不上，就说明
    用户看着的那一版已经被别人改过了（AI 刚落库、另一个标签页），这一笔不落，由用户自己决定
    刷新还是重写。两者都得说给用户听，前端要按状态码走两条不同的出路，所以不能都用 409。
    clientUpdatedAt 是**不透明令牌**，原样收、原样比，不要当时间戳解析（微秒会掉）。
    """
    run = await read_run(request.state.user_id, novelId)
    # 空章号两边都不算数：标记里还没有目标章（闲聊那一轮、或 resolve 还没跑到）时不该挡人，
    # 请求里带了空 chapterId 也一样 —— 两个空串相等，不这么写就会凭空 409。
    running_chapter = (run or {}).get("chapterId") if (run or {}).get("status") == RUNNING else ""
    if chapterId and running_chapter and running_chapter == chapterId:
        raise HTTPException(
            status_code=409, detail="AI 正在写这一章，等它写完确认后再改，或先停止生成"
        )

    async with pg_pool.connection() as conn:
        await _require_novel(conn, novelId, request.state.user_id)

        async with conn.transaction():
            # 一条语句同时问出两件事：这一章还在不在（found），以及版本对不对（new_at 是不是空）。
            # 不用"先查再改"：那样中间有窗口；这里靠 UPDATE 自己重判 WHERE，同一时刻只可能有一个
            # 写进去，另一个落到"存在但没命中"，正好是版本闸要挡的那个 412。
            try:
                cur = await conn.execute(
                    'WITH target AS ('
                    '  SELECT "updatedAt" AS seen FROM novel_chapter WHERE id = %s AND "novelId" = %s'
                    '), upd AS ('
                    '  UPDATE novel_chapter c SET content = %s, "wordCount" = %s, "updatedAt" = now() '
                    '  FROM target t WHERE c.id = %s AND t.seen = %s::timestamptz '
                    '  RETURNING c."updatedAt" AS new_at, c."wordCount" AS wc'
                    ') '
                    'SELECT (SELECT count(*) FROM target) AS found, '
                    '(SELECT new_at FROM upd) AS new_at, (SELECT wc FROM upd) AS wc',
                    (
                        chapterId,
                        novelId,
                        content,
                        count_chapter_words(content),
                        chapterId,
                        clientUpdatedAt,
                    ),
                )
                found, new_at, word_count = await cur.fetchone()
            except DataError:
                # 令牌不是一个时间戳（前端传坏了）：它跟哪一版都不相等，按"版本对不上"处理，
                # 别把一条数据库类型错误当成 500 抛出去。
                raise HTTPException(status_code=412, detail="这章已被改动，请刷新后重试") from None
            total = None
            if new_at is not None:
                cur = await conn.execute(NOVEL_WORD_COUNT_SQL, (novelId, novelId))
                total = await cur.fetchone()

    if not found:
        raise HTTPException(status_code=404, detail="章节不存在")
    if new_at is None:
        raise HTTPException(status_code=412, detail="这章已被改动，请刷新后重试")
    # 回传这一章的新字数与全书总字数：前端就地改这两个数，不重拉书架
    # （重拉会把正在看的正文清空，正文是另一个接口按章取的）。
    # updatedAt 同时是下一次保存要带回来的版本令牌，前端得原样存着。
    return {
        "chapterId": chapterId,
        "updatedAt": new_at,
        "wordCount": word_count,
        "novelWordCount": total[0] if total else 0,
    }


@router.patch("/chapter")
async def rename_chapter(
    request: Request,
    novelId: str = Form(..., description="小说 ID（也就是 threadId）"),
    chapterId: str = Form(..., description="章节 ID"),
    title: str = Form(..., description="新章名"),
):
    """改章名。只动 title 与 updatedAt，正文、精简、台账一概不碰。

    这一笔也 bump updatedAt，所以必须把它回传：前端手上那份版本令牌跟着换新，否则用户改个
    章名之后第一次手改正文就会被版本闸当成冲突挡下来。
    """
    title = title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="章节标题不能为空")

    async with pg_pool.connection() as conn:
        await _require_novel(conn, novelId, request.state.user_id)

        cur = await conn.execute(
            'UPDATE novel_chapter SET title = %s, "updatedAt" = now() '
            'WHERE id = %s AND "novelId" = %s RETURNING title, "updatedAt"',
            (title, chapterId, novelId),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"chapterId": chapterId, "title": row[0], "updatedAt": row[1]}


@router.delete("/chapter")
async def delete_chapter(
    request: Request,
    novelId: str = Query(..., description="小说 ID（也就是 threadId）"),
    chapterId: str = Query(..., description="章节 ID"),
):
    """删一章，同事务里把全书总字数减回来。

    这一章挂的台账靠外键 ON DELETE CASCADE 一并没了，不用逐表删；留下的序号空洞由
    chapter_information 的"取序号小于目标的前两章"兜着，不重排。
    """
    async with pg_pool.connection() as conn:
        await _require_novel(conn, novelId, request.state.user_id)

        async with conn.transaction():
            cur = await conn.execute(
                'DELETE FROM novel_chapter WHERE id = %s AND "novelId" = %s RETURNING "order"',
                (chapterId, novelId),
            )
            row = await cur.fetchone()
            total = None
            if row is not None:
                cur = await conn.execute(NOVEL_WORD_COUNT_SQL, (novelId, novelId))
                total = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {
        "chapterId": chapterId,
        "order": row[0],
        "novelWordCount": total[0] if total else 0,
    }


@router.patch("/novel")
async def edit_novel_meta(
    request: Request,
    novelId: str = Form(..., description="小说 ID（也就是 threadId）"),
    title: str | None = Form(None, description="新书名，不传就不动"),
    tropes: str | None = Form(None, description="新的类型 / 套路，不传就不动"),
    style: str | None = Form(None, description="新的文风，不传就不动"),
    reviewEnabled: str | None = Form(None, description="是否开启 AI 审稿：true / false，不传就不动"),
):
    """改书名 / 类型 / 文风 / AI 审稿开关：只改传上来的那几项，没传的原样留着。"""
    fields: list[tuple[str, object]] = []
    if title is not None:
        title = title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="书名不能为空")
        fields.append(("title", title))
    if tropes is not None:
        fields.append(("tropes", tropes.strip()))
    if style is not None:
        fields.append(("style", style.strip()))
    if reviewEnabled is not None:
        value = reviewEnabled.strip().lower()
        if value not in ("true", "false"):
            raise HTTPException(status_code=400, detail="reviewEnabled 只能是 true 或 false")
        fields.append(("reviewEnabled", value == "true"))
    if not fields:
        raise HTTPException(status_code=400, detail="没有要改的内容")

    # 列名取自上面写死的四个，没有一个字来自请求，所以这里的拼接安全；值一律走 %s。
    assignments = ", ".join(f'"{column}" = %s' for column, _ in fields)
    params = [value for _, value in fields] + [novelId, request.state.user_id]

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            f'UPDATE novel SET {assignments}, "updatedAt" = now() '
            'WHERE id = %s AND "userId" = %s RETURNING title, tropes, style, "reviewEnabled"',
            tuple(params),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {
        "novelId": novelId,
        "title": row[0] or "",
        "tropes": row[1] or "",
        "style": row[2] or "",
        "reviewEnabled": True if row[3] is None else bool(row[3]),
    }


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

    这一笔也 bump updatedAt（裸 SQL 不认 prisma 的 @updatedAt），所以要回传新值，理由同改章名。
    """
    if status not in CHAPTER_STATUSES:
        raise HTTPException(status_code=400, detail="未知的章节状态")

    async with pg_pool.connection() as conn:
        await _require_novel(conn, novelId, request.state.user_id)

        cur = await conn.execute(
            'UPDATE novel_chapter SET status = %s, "updatedAt" = now() '
            'WHERE id = %s AND "novelId" = %s RETURNING status, "updatedAt"',
            (status, chapterId, novelId),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"chapterId": chapterId, "status": row[0], "updatedAt": row[1]}


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


@router.post("/inspiration")
async def create_inspirations(
    request: Request,
    novelId: str = Form(..., description="小说 ID（也就是 threadId）"),
    category: list[str] = Form(
        ["other"],
        description="内容类型（可多选，尽量少选）：style/plot/character/meme/setting/scene/"
        "dialogue/imagery/emotion/technique/other",
    ),
    usage: str = Form(
        "", description="使用策略：must 必用 / selectable 选用 / never 不用；留空按分类默认（风格必用、其余选用）"
    ),
    inspirations: str = Form("[]", description="素材元信息 JSON 数组，一次只收一条"),
    files: list[UploadFile] = File(default=[]),
):
    """往这本书的灵感库里加**一条**素材（文件 / 链接 / 文本），落库时按用户选的**每个分类各生成一条**灵感。

    与 /run 挂素材同一个解析口径（parse_items），只是这里直接落库、不进图。一次只收一条素材：多传
    直接 400。翻译模型按分类逐条提炼 title / scenario / digest，每条的 category 只归它自己那个分类；
    usage 统一用用户选的（留空按分类默认）；lifecycle 按分类自动定、用户改不了（见 inspiration.py）。
    新建各行（可能不止一条）的 id 由响应带回。
    """
    categories = _clean_categories(category)
    usage_value = _clean_usage(usage) if usage else None

    async with pg_pool.connection() as conn:
        await _require_novel(conn, novelId, request.state.user_id)

    items = await parse_items(inspirations, files)
    if len(items) != 1:
        raise HTTPException(status_code=400, detail="一次只能添加一条灵感")

    source = items[0]
    content = source.get("content") or ""
    translated = await translate(content, categories)

    # 翻译是最慢的一段：跑完再看一眼客户端还在不在。用户关窗 / 取消会 abort 掉请求，
    # 这时别再落库 —— 否则"点了取消却凭空多出一条灵感"会很别扭。
    if await request.is_disconnected():
        raise HTTPException(status_code=499, detail="客户端已取消")

    by_cat = {t["category"]: t for t in translated if t.get("category")}

    created = [
        {
            "type": source.get("type") or "file",
            "name": source.get("name") or "",
            "content": content,
            "title": (by_cat.get(cat) or {}).get("title") or source.get("name") or "",
            "scenario": (by_cat.get(cat) or {}).get("scenario") or "",
            "digest": (by_cat.get(cat) or {}).get("digest") or "",
            "category": [cat],
            "usage": usage_value,
        }
        for cat in categories
    ]
    written = await add_inspirations(novelId, created)
    return {"threadId": novelId, "created": written}


@router.post("/inspiration/translate")
async def retranslate_inspiration(
    request: Request,
    novelId: str = Form(..., description="小说 ID（也就是 threadId）"),
    inspirationId: list[str] = Form(..., description="这份素材现有的行 id（同一 sourceId 的多条）"),
    category: list[str] = Form(default=[], description="这份素材要保留的标签；按它重建灵感"),
):
    """重新翻译一份素材：按素材卡上选的标签重跑模型，重新派生这份素材产出的灵感（缺的补、多的删）。

    标签是重建的依据，所以至少选一个。已有行按标签就地复用（usage / lifecycle / usedChapterIds 保留），
    只重写标题 / 场景 / 写作指引。详见 inspiration.py 的 reconcile_inspirations。
    """
    if not [i for i in inspirationId if i]:
        raise HTTPException(status_code=400, detail="缺少灵感 id")
    wanted = _clean_categories(category)
    if not wanted:
        raise HTTPException(status_code=400, detail="至少选一个标签")

    async with pg_pool.connection() as conn:
        await _require_novel(conn, novelId, request.state.user_id)

    result = await reconcile_inspirations(novelId, inspirationId, wanted)
    if not result:
        raise HTTPException(status_code=404, detail="灵感不存在")
    return {"threadId": novelId, "ids": result}


@router.patch("/inspiration")
async def edit_inspiration(
    request: Request,
    novelId: str = Form(..., description="小说 ID（也就是 threadId）"),
    inspirationId: str = Form(..., description="要改的那条灵感的行 id"),
    category: list[str] | None = Form(None, description="新的内容类型（可多值）；不传不改"),
    usage: str = Form("", description="使用策略：must/selectable/never；不传不改"),
):
    """改一条灵感的类型 / 使用策略（卡片上就地改）。内容与翻译结果一概不碰，生命周期固定、改不了。"""
    sets: list[str] = []
    params: list = []
    if category is not None:
        sets.append("category = %s")
        params.append(_clean_categories(category))
    if usage:
        sets.append("usage = %s")
        params.append(_clean_usage(usage))
    if not sets:
        raise HTTPException(status_code=400, detail="没有要改的字段")
    sets.append('"updatedAt" = now()')
    params.extend([inspirationId, novelId])

    async with pg_pool.connection() as conn:
        await _require_novel(conn, novelId, request.state.user_id)
        cur = await conn.execute(
            f'UPDATE novel_inspiration SET {", ".join(sets)} '
            'WHERE id = %s AND "novelId" = %s RETURNING id, category, usage, lifecycle',
            tuple(params),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="灵感不存在")
    return {"id": row[0], "category": row[1], "usage": row[2], "lifecycle": row[3]}


@router.delete("/inspiration")
async def delete_inspiration(
    request: Request,
    novelId: str = Query(..., description="小说 ID（也就是 threadId）"),
    inspirationId: list[str] = Query(..., description="要删的行 id（可多条，同一份素材一起删）"),
):
    """删一份素材产出的灵感（一条或多条）。usedChapterIds 只是 id 列表，没有外键，删掉这些不影响章节。"""
    ids = [i for i in inspirationId if i]
    if not ids:
        raise HTTPException(status_code=400, detail="缺少灵感 id")
    async with pg_pool.connection() as conn:
        await _require_novel(conn, novelId, request.state.user_id)
        cur = await conn.execute(
            'DELETE FROM novel_inspiration WHERE id = ANY(%s) AND "novelId" = %s RETURNING id',
            (ids, novelId),
        )
        deleted = [row[0] for row in await cur.fetchall()]
    return {"deleted": deleted}
