"""章节的读写，外加动笔前要备齐的那几样材料。

写：upsert_chapter 落这一章、同一事务里重算全书总字数、把台账交给 ledger.py 落库；
序号由库里现算（最大序号 + 1），不接受调用方指定。
读：get_writer_context 一次取回上一章全文、上上一章精简、上一章 pastSummary、本章生效的
大纲与世界规则、已有设定目录。写新章不传序号（取"下一章"），改已有章节传目标序号 ——
目标章由 get_chapter_order 按 id 认（前端手上只有它点开的那一章的 id）。
物品、势力、配角、关系、时间线这些一章未必用得上，交给 writer 用 fetchDB 点查。
"""
import json
import re
import uuid

from .ledger import CATALOG, CATALOG_SQL, TITLE_LINE, render_catalog, write_ledger, write_lines

# 番茄最佳阅读长度，writer 照这个写，reader 审稿时按这个卡字数。
CHAPTER_MIN_WORDS = 2200
CHAPTER_MAX_WORDS = 2800

# 一条支线（临时小剧情）最多写几章就必须收尾、收束回主线，防止写手顺着一个剧情一直写。
# 到点由 planner 用确定的数报给写手（见 nodes/writer/helpers.py 的 _constraint_block），不由模型自己拿捏。
BRANCH_MAX_CHAPTERS = 3

# 一条阶段线（主线下的一个大阶段）最多写几章就必须收尾、再开下一条阶段线。比支线长，
# 一条阶段线里约容纳 (PHASE_MAX_CHAPTERS / BRANCH_MAX_CHAPTERS) 条支线。同样由 planner 照硬数报。
PHASE_MAX_CHAPTERS = 6

# 大纲 / 世界规则塞进 prompt 前的上限，别一条把上下文吃光；上一章正文不设上限（截了等于没读）。
MAX_OUTLINE_CHARS = 6_000
MAX_RULE_CHARS = 2_000

NEXT_ORDER_SQL = 'SELECT COALESCE(MAX("order"), 0) + 1 FROM novel_chapter WHERE "novelId" = %s'

# 上一章取正文、精简和 pastSummary，上上一章只要精简 —— 再往前的内容早进了 pastSummary。
# 取"严格小于目标序号里最大的两条"，不写死 order-1 / order-2：中间删过章就会有空洞，
# 写死会让 prev_content 落空，模型被告知"这是本书第一章，没有上一章可接"。
PREV_CHAPTERS_SQL = (
    'SELECT "order", content, summary, "pastSummary" FROM novel_chapter '
    'WHERE "novelId" = %s AND "order" < %s ORDER BY "order" DESC LIMIT 2'
)

# 大纲 / 世界规则用 startChapterId / endChapterId 圈生效区间，两列存的是章节 id，要比就得
# 解析回 order（调用方给的是"下一章的序号"，那一章还没有 id）。区间为空 = 整本通用；
# 左连接落空（没设，或指向的章已删）都按「不限」处理，不让一处悬空把整条大纲都挡掉。
# level 区分主线 / 阶段线 / 支线；parentId 表达包含关系（阶段线挂主线、支线挂阶段线，
# 主线为空）；start_order 是起始章的序号，阶段线 / 支线靠它算「已经写了几章」。
OUTLINES_SQL = (
    'SELECT o.id, o.level, o.content, o."parentId", sc."order" FROM novel_outline o '
    'LEFT JOIN novel_chapter sc ON sc.id = o."startChapterId" '
    'LEFT JOIN novel_chapter ec ON ec.id = o."endChapterId" '
    'WHERE o."novelId" = %s AND (sc."order" IS NULL OR sc."order" <= %s) '
    'AND (ec."order" IS NULL OR ec."order" >= %s) ORDER BY o."order"'
)

WORLD_RULES_SQL = (
    'SELECT r.name, r.rule FROM novel_world_rule r '
    'LEFT JOIN novel_chapter sc ON sc.id = r."startChapterId" '
    'LEFT JOIN novel_chapter ec ON ec.id = r."endChapterId" '
    'WHERE r."novelId" = %s AND (sc."order" IS NULL OR sc."order" <= %s) '
    'AND (ec."order" IS NULL OR ec."order" >= %s) ORDER BY r."createdAt"'
)

# novel_chapter 上 (novelId, order) 唯一，按这两个键 upsert：同一章重跑不会插出两行。
# 冲突时**一个字都不动 title**：writer 写新章时 chapter_id 恒为空、靠这个冲突键复用已有的行，
# 所以"改这一章"走的正是 UPDATE 这一路 —— 从前这里写着 title = EXCLUDED.title，用户手改过的
# 章名会被 AI 重发的那一份冲掉。新章走 INSERT 那条路，标题照旧由 AI 起。
UPSERT_SQL = (
    'INSERT INTO novel_chapter (id, "novelId", title, "order", status, content, '
    '"pastSummary", summary, "wordCount", "createdAt", "updatedAt") '
    "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, now(), now()) "
    'ON CONFLICT ("novelId", "order") DO UPDATE SET '
    "status = EXCLUDED.status, content = EXCLUDED.content, "
    '"pastSummary" = EXCLUDED."pastSummary", summary = EXCLUDED.summary, '
    '"wordCount" = EXCLUDED."wordCount", "updatedAt" = now() '
    "RETURNING id"
)

# 全书总字数按章节 SUM，不做加减：重跑走的是 UPSERT 的 UPDATE 那条路，增量会重复计。
NOVEL_WORD_COUNT_SQL = (
    'UPDATE novel SET "wordCount" = '
    '(SELECT COALESCE(SUM("wordCount"), 0) FROM novel_chapter WHERE "novelId" = %s), '
    '"updatedAt" = now() WHERE id = %s RETURNING "wordCount"'
)

_MARKDOWN = (
    (re.compile(r"#{1,6}\s*"), ""),
    (re.compile(r"\*\*(.*?)\*\*"), r"\1"),
    (re.compile(r"\*(.*?)\*"), r"\1"),
    (re.compile(r"~~(.*?)~~"), r"\1"),
    (re.compile(r"`(.*?)`"), r"\1"),
    (re.compile(r"\[(.*?)\]\(.*?\)"), r"\1"),
)


def count_chapter_words(content: str) -> int:
    """数一章正文的中文字数，口径与 writerSkill 的 check_chapter_wordcount.py 一致。

    去掉 markdown 标记，并跳过第一个以 # 开头又带「章」字的行（那是标题行，不算正文）。
    """
    lines = (content or "").split("\n")
    for i, line in enumerate(lines):
        if line.startswith("#") and "章" in line:
            content = "\n".join(lines[i + 1 :])
            break

    for pattern, repl in _MARKDOWN:
        content = pattern.sub(repl, content)
    return len(re.findall(r"[一-鿿]", content))


def split_title(content: str) -> tuple[str, str]:
    """正文 → (摘掉标题行的正文, 标题)。找不到标题行就是 (原文, "")。

    标题那行（`# 第X章 标题`）单独存 novel_chapter.title：页面上标题栏与正文区都在，
    正文里再留一份就是同一句话显示两遍。writer 的 save 与 editor 的 collect 都走这里，
    规则共用 ledger.TITLE_LINE —— 流式层按同一条摘同一行，用户看到的与存进库的才对得上。
    标题连着它后面的空行一起摘（那空行是给标题留的，正文不需要）。
    """
    text = content or ""
    match = TITLE_LINE.search(text)
    if match is None:
        return text, ""
    stop = match.end()
    while stop < len(text) and text[stop] == "\n":
        stop += 1
    return text[: match.start()] + text[stop:], match.group(1).strip()


def _clip(text: str, limit: int) -> str:
    """长文本截到上限，截了就注明，免得模型以为那就写完了。"""
    text = text or ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…（原 {len(text)} 字符，已截断）"


# 章节清单只给序号和标题，正文由定位到目标那一章时单独取。
CHAPTER_LIST_SQL = (
    'SELECT id, "order", title FROM novel_chapter WHERE "novelId" = %s ORDER BY "order"'
)
MAX_CHAPTER_LIST_CHARS = 4_000

# 改章节时要取的那一行：改稿时除了正文，其余原样沿用。
CHAPTER_ROW_SQL = (
    'SELECT id, title, "order", status, content, summary, "pastSummary" '
    'FROM novel_chapter WHERE "novelId" = %s AND "order" = %s'
)

# 按 id 认目标章：前端手上只有它点开的那一章的 id。
CHAPTER_ORDER_BY_ID_SQL = (
    'SELECT id, "order" FROM novel_chapter WHERE "novelId" = %s AND id = %s'
)


async def _next_order(conn, novel_id: str) -> int:
    cur = await conn.execute(NEXT_ORDER_SQL, (novel_id,))
    row = await cur.fetchone()
    return row[0] if row else 1


async def list_chapters(novel_id: str) -> str:
    """这本书的章节清单，排成给模型看的几行（序号 + 标题）；空书给空串。"""
    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(CHAPTER_LIST_SQL, (novel_id,))
        rows = await cur.fetchall()

    lines = [f"- 第 {order} 章 {title or '未命名'}" for _id, order, title in rows]
    text = "\n".join(lines)
    if len(text) > MAX_CHAPTER_LIST_CHARS:
        text = text[:MAX_CHAPTER_LIST_CHARS] + f"\n…（共 {len(lines)} 章，只列到这里）"
    return text


async def get_chapter(novel_id: str, order: int) -> dict | None:
    """按序号取这一章，库里没有就给 None。字段与 ChapterMeta 对齐。"""
    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(CHAPTER_ROW_SQL, (novel_id, order))
        row = await cur.fetchone()
    if row is None:
        return None

    chapter_id, title, order, status, content, summary, past_summary = row
    return {
        "chapter_id": chapter_id,
        "chapter_title": title or "",
        "chapter_order": order,
        "chapter_status": status or "draft",
        "chapter_content": content or "",
        "chapter_summary": summary or "",
        "past_summary": past_summary or {},
    }


async def get_chapter_order(novel_id: str, chapter_id: str) -> int | None:
    """按章节 id 取它的序号，库里没有（本地新建没落库、已经删了）就给 None。

    请求里带的是章节 id：中间插了一章之后序号会整体后移，靠"第几章"认目标迟早认错人。
    """
    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(CHAPTER_ORDER_BY_ID_SQL, (novel_id, chapter_id))
        row = await cur.fetchone()
    return row[1] if row else None


async def next_chapter_order(novel_id: str) -> int:
    """这本书下一章该用的序号（最大序号 + 1），还没有章节就是 1。"""
    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        return await _next_order(conn, novel_id)


async def get_writer_context(novel_id: str, order: int | None = None) -> dict:
    """动笔前要备齐的材料：本章序号、前文、本章生效的大纲与世界规则、已有设定目录。

    不传 order 就是"下一章"（writer 写新章）；改已有章节传目标序号 —— "上一章"该是它前面
    那一章，大纲与世界规则也要按它当时生效的那几条取。前文没有就是空串 / 空 dict。
    大纲按 level 分成主线段（main_outlines）、阶段线段（phase_lines）、支线段（branch_lines），
    支线带 start_order，供 planner 算它已经写了几章。阶段线 / 支线各带 parent_id（阶段线挂主线、
    支线挂阶段线），main_line_id 是主线的 id，供 planner 新开阶段线时挂父。prev_summary 是上一章
    精简，喂给写手当近章记忆；prev_content 是上一章全文，只留给 reader 核对承接。目录（各给 id
    和名字）是给 writer 的台账用的：它得知道"这一章用的是已有的哪一条"。
    """
    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        if order is None:
            order = await _next_order(conn, novel_id)

        cur = await conn.execute(PREV_CHAPTERS_SQL, (novel_id, order))
        prev_content = ""
        prev_summary = ""
        prev_prev_summary = ""
        prev_past_summary = {}
        # 按行序认：第一条是上一章，第二条是上上一章（查询已按 order 倒序）。
        for index, (_order, content, summary, past_summary) in enumerate(await cur.fetchall()):
            if index == 0:
                prev_content = content or ""
                prev_summary = summary or ""
                prev_past_summary = past_summary or {}
            else:
                prev_prev_summary = summary or ""

        # 大纲按 level 拆开：主线当脉，阶段线是这一段主线要推进的方向，支线是当前那个临时小剧情。
        # parentId 带着包含关系：阶段线挂主线、支线挂阶段线。main_line_id 取第一条主线的 id，
        # 供 writer 新开阶段线时挂父（setup 收的「核心冲突」暂只一条）。
        cur = await conn.execute(OUTLINES_SQL, (novel_id, order, order))
        main_outlines = []
        main_line_id = ""
        phase_lines = []
        branch_lines = []
        for outline_id, level, content, parent_id, start_order in await cur.fetchall():
            text = _clip(content, MAX_OUTLINE_CHARS)
            if level == "phase":
                phase_lines.append(
                    {"id": outline_id, "content": text, "start_order": start_order, "parent_id": parent_id or ""}
                )
            elif level == "branch":
                branch_lines.append(
                    {"id": outline_id, "content": text, "start_order": start_order, "parent_id": parent_id or ""}
                )
            else:
                main_outlines.append(text)
                if not main_line_id:
                    main_line_id = outline_id

        cur = await conn.execute(WORLD_RULES_SQL, (novel_id, order, order))
        world_rules = [
            {"name": name or "", "rule": _clip(rule, MAX_RULE_CHARS)}
            for name, rule in await cur.fetchall()
        ]

        # 目录每个 UNION 分支都要书号，绑定参数的个数跟着 CATALOG 的条数走。
        cur = await conn.execute(CATALOG_SQL, (novel_id,) * len(CATALOG))
        catalog = render_catalog(await cur.fetchall())

    return {
        "chapter_order": order,
        # 上一章全文只给 reader 核对承接用；写手看的是 prev_summary（近章摘要）。
        "prev_content": prev_content,
        "prev_summary": prev_summary,
        "prev_prev_summary": prev_prev_summary,
        "prev_past_summary": prev_past_summary,
        "main_outlines": main_outlines,
        "main_line_id": main_line_id,
        "phase_lines": phase_lines,
        "branch_lines": branch_lines,
        "world_rules": world_rules,
        "catalog": catalog,
    }


async def upsert_chapter(novel_id: str, chapter: dict) -> tuple[str, int]:
    """把一章写进 novel_chapter，顺带刷新全书总字数、落这一章的台账（关联 + 阶段线/支线）。

    入参是 ChapterMeta 那份 dict，字数落库前调用方要自己算好。
    四笔同一事务：总字数没跟上前端就对不上，台账没跟上将来改设定就查不出这一章用了什么；
    台账要 chapter_id，所以排在章节插入之后。

    已存在的章不会被改标题（见 UPSERT_SQL 上面那段）：用户改过的章名以库里那份为准。
    """
    from api.utils.db import pg_pool

    chapter_id = chapter.get("chapter_id") or uuid.uuid4().hex
    async with pg_pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                UPSERT_SQL,
                (
                    chapter_id,
                    novel_id,
                    chapter.get("chapter_title") or "",
                    chapter.get("chapter_order"),
                    chapter.get("chapter_status") or "draft",
                    chapter.get("chapter_content") or "",
                    json.dumps(chapter.get("past_summary") or {}, ensure_ascii=False),
                    chapter.get("chapter_summary") or "",
                    chapter.get("chapter_word_count") or 0,
                ),
            )
            row = await cur.fetchone()
            chapter_id = row[0]

            await write_ledger(
                conn,
                novel_id,
                chapter_id,
                chapter.get("chapter_refs"),
                chapter.get("chapter_new"),
            )

            await write_lines(
                conn,
                novel_id,
                chapter_id,
                chapter.get("chapter_order") or 0,
                chapter.get("chapter_lines"),
            )

            cur = await conn.execute(NOVEL_WORD_COUNT_SQL, (novel_id, novel_id))
            total = await cur.fetchone()
    return chapter_id, total[0] if total else 0
