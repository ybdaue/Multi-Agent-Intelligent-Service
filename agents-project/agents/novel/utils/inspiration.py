"""灵感素材：用户在灵感库挂的文件 / 链接 / 文本，落 novel_inspiration，并给写作链提供"用哪些灵感"。

两条命一分为二：**入库**时把原文交给模型翻译出「标题 / 使用场景 / 写作指引(digest)」（`translate`）；
**写章**时按使用策略与生命周期把库内的灵感挑出来（`fetch_inspiration_menu` / `fetch_inspirations`）。

使用策略 usage（must 必用 / selectable 选用 / never 不用）与生命周期 lifecycle（reuse 复用 /
once 单次）都由用户在灵感库里定；新建时按分类给默认（风格默认必用，其余默认选用；引子型
——剧情 / 人物 / 设定——默认单次，其余默认复用）。哪几章用过由 update 落章后补
（`mark_used`）—— 单次灵感一旦用过就退出候选。

灵感不再从对话框上传：会话里挑中的是库里已有的行（`fetch_inspirations` 按 id 取回），
随 `state.inspirations` 进图。`render_inspirations` 仍把它渲染进提示词。
"""
import json
import uuid

from fastapi import UploadFile
from langchain_core.messages import HumanMessage, SystemMessage

from agents.utils.models import ainvoke_with_fallback, parse_json_value

from .model import BackupMainModel, MainModel
from .prompt import INSPIRATION_PROMPT

# 一条素材进 prompt 的字符上限：附件正文可能很长，别一条把上下文吃光。
MAX_INSPIRATION_CHARS = 4_000
# 单个上传件读取上限：再大就不是"给模型看的素材"了。
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
# 文本类附件的扩展名兜底：content_type 未必准（txt 传成 octet-stream 很常见）。
_TEXT_EXT = (".md", ".txt", ".json", ".csv", ".html", ".htm", ".log", ".yml", ".yaml")

# 给用户看的形态名，与前端 InspirationItem.kind 对应（image 只为兼容老数据保留）。
_KIND_LABEL = {"image": "图片", "file": "文件", "url": "链接", "text": "文本"}

# 内容类型的中文名，翻译提示词里用（与前端 types.ts 的 INSPIRATION_CATEGORY_LABEL 对齐）。
CATEGORY_LABEL = {
    "style": "风格",
    "plot": "剧情",
    "character": "人物",
    "meme": "热梗",
    "setting": "设定",
    "scene": "场景",
    "dialogue": "对话",
    "imagery": "意象",
    "emotion": "情感",
    "technique": "写作技巧",
    "other": "其他",
}

_INSERT_SQL = (
    'INSERT INTO novel_inspiration (id, "novelId", "sourceId", title, category, type, content, '
    'usage, lifecycle, scenario, digest, "usedChapterIds", "createdAt", "updatedAt") '
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())"
)

# 追加而不是覆盖：同一条素材可能被好几章用到。
_USED_SQL = (
    'UPDATE novel_inspiration SET "usedChapterIds" = array_append("usedChapterIds", %s), '
    '"updatedAt" = now() WHERE id = ANY(%s) AND NOT ("usedChapterIds" @> ARRAY[%s]::text[])'
)

# 挑灵感 / 取灵感要出的列（键即库里的列名）。usedChapterIds 让 planner 看得见"用过没有"。
# sourceId 让前端把同一份素材产出的多条灵感并进一张卡。
_INSP_COLUMNS = (
    "id", "sourceId", "title", "category", "type", "content",
    "usage", "lifecycle", "scenario", "digest", "usedChapterIds",
)

# 翻译模型：小提示词 + JSON 出参，稳定优先，非流式。显式设超时，别让一条慢请求把整次新增卡死
# （之前没设超时，前端那条 10s 的转发会先一步断开、报"后端响应超时"，见 BFF 的 inspiration 路由）。
try:
    _insp_model = MainModel(temperature=0.3, disable_streaming=True, timeout=60, max_retries=0)
    _insp_model_backup = BackupMainModel(
        temperature=0.3, disable_streaming=True, timeout=60, max_retries=0
    )
except Exception:
    _insp_model = None
    _insp_model_backup = None


async def _attachment(file: UploadFile) -> str:
    """一个上传转成给模型看的文字；图片与二进制只说"有这么个文件，看不了内容"。

    模型是纯文本的，没有 vision —— 图片硬塞字节没有意义，如实告诉它读不了，免得它以为看过。
    """
    name = (file.filename or "").strip()
    content_type = (file.content_type or "").lower()
    if not (content_type.startswith("text/") or name.lower().endswith(_TEXT_EXT)):
        kind = "图片" if content_type.startswith("image/") else f"{content_type or '未知类型'} 文件"
        return f"（{kind}，看不了内容）"

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return "（文件过大，未读取）"
    text = data.decode("utf-8", errors="replace")
    return text[:MAX_INSPIRATION_CHARS] + (
        "…（已截断）" if len(text) > MAX_INSPIRATION_CHARS else ""
    )


async def parse_items(meta: str, files: list[UploadFile]) -> list[dict]:
    """这一批素材：前端的元信息 + 上传件的内容（能读的才读），配成能落库的条目。

    meta 是 JSON 数组，字段与前端 InspirationItem 对齐（kind / name / url / text / hasFile）。
    带 hasFile 的那几条与 files **同序**（前端两个数组一起拼的），按顺序配回去；链接 / 文本没有上传件。
    """
    try:
        parsed = json.loads(meta or "[]")
    except ValueError:
        parsed = []
    if not isinstance(parsed, list):
        parsed = []

    pending = list(files)
    items = []
    for raw in parsed:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "file")
        name = str(raw.get("name") or "").strip() or "未命名"
        if kind == "url":
            content = str(raw.get("url") or "").strip()
        elif kind == "text":
            content = str(raw.get("text") or "")
        elif raw.get("hasFile") and pending:
            content = await _attachment(pending.pop(0))
        else:
            content = "（没收到这个文件）"
        items.append({"type": kind, "name": name, "content": content})
    return items


async def translate(content: str, categories: list[str] | None = None) -> list[dict]:
    """把一条灵感原文交给模型，**按用户选的每个分类各提炼一条**灵感。

    模型产出一个 JSON 对象，键是分类代号、值是该分类的 {title, scenario, digest}（用户没选的
    分类不该出现）。这里统一转成 [{category, title, scenario, digest}, ...] 返回，只保留认得出
    的分类；也兼容模型给数组（每项带 category）的情况。失败 / 解不出 JSON 一律给空列表 ——
    调用方兜底（title 退回原名、scenario / digest 留空），别为一次翻译把新增卡住。
    """
    cats = [c for c in (categories or []) if c] or ["other"]
    if _insp_model is None or not (content or "").strip():
        return []
    asked_cats = "、".join(f"{CATEGORY_LABEL.get(c, c)}({c})" for c in cats)
    asked = f"用户给这条灵感选的分类：{asked_cats}\n\n灵感原文：\n\n{content}"
    try:
        reply = await ainvoke_with_fallback(
            _insp_model, _insp_model_backup,
            [SystemMessage(content=INSPIRATION_PROMPT), HumanMessage(content=asked)],
        )
    except Exception:
        return []
    text = reply.content if isinstance(reply.content, str) else ""
    try:
        value = parse_json_value(text)
    except (ValueError, TypeError):
        return []

    # 期望 {"plot": {title, scenario, digest}, "character": {...}}；也兼容数组（每项带 category）。
    entries: list[tuple[str, dict]] = []
    if isinstance(value, dict):
        entries = [(str(k), v if isinstance(v, dict) else {}) for k, v in value.items()]
    elif isinstance(value, list):
        entries = [(str(r.get("category") or ""), r) for r in value if isinstance(r, dict)]
    else:
        return []

    out: list[dict] = []
    for cat, body in entries:
        cat = cat.strip()
        if cat not in CATEGORY_LABEL:
            continue
        out.append({
            "category": cat,
            "title": str(body.get("title") or "").strip(),
            "scenario": str(body.get("scenario") or "").strip(),
            "digest": str(body.get("digest") or "").strip(),
        })
    return out


# 引子型：用过一次就把产出交给台账 / 数据库（人物进 novel_character、设定进各设定表、
# 剧情进大纲的阶段线 / 支线），灵感本身退出候选。其余是素材型，一直可被再选用。
SEED_LIFECYCLE = {"plot", "character", "setting"}


def default_lifecycle(categories: list[str] | None) -> str:
    """新增灵感的生命周期默认值：引子型（剧情 / 人物 / 设定）默认单次，其余默认复用。"""
    return "once" if SEED_LIFECYCLE & set(categories or []) else "reuse"


def default_usage(categories: list[str] | None) -> str:
    """新增灵感的使用策略默认值：风格默认必用，其余默认选用（由用户自己决定改"不用"）。"""
    return "must" if "style" in (categories or []) else "selectable"


async def add_inspirations(novel_id: str, items: list[dict]) -> list[dict]:
    """这一批灵感落库，回填每条的 id（空列表不碰库）。

    每条自带各自的 category（按标签逐条产出，一条只归一个分类）；items 各条可带 title /
    scenario / digest / usage / lifecycle，缺的走兜底：title 退回 name、usage 按分类定（风格
    必用、其余选用）、lifecycle 按分类定（引子型单次、其余复用）。
    """
    if not items:
        return []

    from api.utils.db import pg_pool

    # 一次调用 = 一份素材（前端一次只收一条），这批行共享同一个 sourceId，前端据此并进一张卡。
    source_id = uuid.uuid4().hex
    written = []
    async with pg_pool.connection() as conn:
        async with conn.transaction():
            for item in items:
                item_id = uuid.uuid4().hex
                cats = list(item.get("category") or []) or ["other"]
                title = (item.get("title") or item.get("name") or "").strip()
                await conn.execute(
                    _INSERT_SQL,
                    (
                        item_id,
                        novel_id,
                        source_id,
                        title,
                        cats,
                        item.get("type") or "file",
                        item.get("content") or "",
                        item.get("usage") or default_usage(cats),
                        item.get("lifecycle") or default_lifecycle(cats),
                        item.get("scenario") or "",
                        item.get("digest") or "",
                        [],
                    ),
                )
                written.append({**item, "id": item_id, "title": title, "category": cats})
    return written


async def reconcile_inspirations(
    novel_id: str, ids: list[str], categories: list[str] | None = None
) -> list[str]:
    """重新翻译一份素材：按标签重跑模型，重新派生这份素材产出的灵感。

    标签取 categories（用户在素材卡上选的）；没给就退回现有各行标签的并集。已有行按标签就地复用
    （**保留 usage / lifecycle / usedChapterIds**，只重写 title / scenario / digest 与 category）；
    标签多出来的新行插入，标签去掉的行删除。原文与形态取自现有行，新行沿用同一 sourceId。
    返回这份素材重建后还剩的行 id（原 ids 都取不到就返回空，交给调用方报 404）。
    """
    ids = [i for i in (ids or []) if i]
    if not ids:
        return []

    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT id, "sourceId", content, type, category FROM novel_inspiration '
            'WHERE id = ANY(%s) AND "novelId" = %s ORDER BY "createdAt", id',
            (ids, novel_id),
        )
        rows = await cur.fetchall()
    if not rows:
        return []

    content = rows[0][2] or ""
    source_id = rows[0][1] or ""
    type_ = rows[0][3] or "file"

    desired: list[str] = []
    for c in categories or []:
        if c in CATEGORY_LABEL and c not in desired:
            desired.append(c)
    if not desired:
        for row in rows:
            for c in row[4] or []:
                if c not in desired:
                    desired.append(c)
    if not desired:
        return []

    translated = await translate(content, desired)
    by_cat = {t["category"]: t for t in translated if t.get("category")}

    # 现有行按标签就地复用：一行归一类，逐类取一条。
    pool = list(rows)
    updates: list[tuple[str, str, str, str, str]] = []
    inserts: list[tuple[str, str, str, str]] = []
    for cat in desired:
        t = by_cat.get(cat) or {}
        title = (t.get("title") or "").strip()
        scenario = (t.get("scenario") or "").strip()
        digest = (t.get("digest") or "").strip()
        hit = next((i for i, r in enumerate(pool) if cat in (r[4] or [])), None)
        if hit is None:
            inserts.append((cat, title, scenario, digest))
        else:
            updates.append((title, scenario, digest, cat, pool.pop(hit)[0]))
    leftover = [r[0] for r in pool]

    result_ids = [row_id for _, _, _, _, row_id in updates]
    async with pg_pool.connection() as conn:
        async with conn.transaction():
            for title, scenario, digest, cat, row_id in updates:
                await conn.execute(
                    'UPDATE novel_inspiration SET '
                    '"title" = COALESCE(NULLIF(%s, \'\'), "title"), scenario = %s, digest = %s, '
                    'category = %s, "updatedAt" = now() WHERE id = %s AND "novelId" = %s',
                    (title, scenario, digest, [cat], row_id, novel_id),
                )
            if leftover:
                await conn.execute(
                    'DELETE FROM novel_inspiration WHERE id = ANY(%s) AND "novelId" = %s',
                    (leftover, novel_id),
                )
            for cat, title, scenario, digest in inserts:
                new_id = uuid.uuid4().hex
                result_ids.append(new_id)
                await conn.execute(
                    _INSERT_SQL,
                    (
                        new_id, novel_id, source_id, title or content[:40], [cat],
                        type_, content, default_usage([cat]), default_lifecycle([cat]),
                        scenario, digest, [],
                    ),
                )
    return result_ids


def _insp_row(row) -> dict:
    """库内一行 → dict（键就是列名），usedChapterIds 换成布尔 used 供菜单展示。"""
    data = dict(zip(_INSP_COLUMNS, row))
    data["used"] = bool(data.get("usedChapterIds"))
    return data


async def fetch_inspirations(novel_id: str, ids: list[str]) -> list[dict]:
    """按 id 集合取回这本书的灵感（对话里挑中的那几条）；id 空就返回空表。"""
    ids = [i for i in (ids or []) if i]
    if not ids:
        return []

    from api.utils.db import pg_pool

    cols = ", ".join(f'"{c}"' for c in _INSP_COLUMNS)
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            f'SELECT {cols} FROM novel_inspiration WHERE "novelId" = %s AND id = ANY(%s)',
            (novel_id, ids),
        )
        rows = await cur.fetchall()
    return [_insp_row(row) for row in rows]


async def fetch_inspiration_menu(novel_id: str) -> dict:
    """写章要用的灵感菜单：{forced, optional}。

    forced = 必用（usage=must）；optional = 选用（usage=selectable）且**没被单次耗掉**
    （lifecycle=once 已用过的排除）。never 两边都不进。单次灵感用过后退出候选，复用的一直可选。

    风格不再是硬规则：新建的风格灵感默认就是 must（default_usage），用户若自己把它改成
    选用 / 不用，这里按用户的选择走 —— 别把"默认值"写死成"强制"。
    """
    from api.utils.db import pg_pool

    cols = ", ".join(f'"{c}"' for c in _INSP_COLUMNS)
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            f'SELECT {cols} FROM novel_inspiration '
            'WHERE "novelId" = %s AND usage IN (\'must\', \'selectable\') '
            'ORDER BY "createdAt"',
            (novel_id,),
        )
        rows = [_insp_row(row) for row in await cur.fetchall()]

    forced: list[dict] = []
    optional: list[dict] = []
    for row in rows:
        if row.get("usage") == "must":
            forced.append(row)
        elif not (row.get("lifecycle") == "once" and row.get("used")):
            optional.append(row)
    return {"forced": forced, "optional": optional}


async def mark_used(inspiration_ids: list[str], chapter_id: str) -> None:
    """把这一章记进那几条素材的 usedChapterIds（这一轮没带灵感就什么都不做）。

    不再按 novelId 收窄：id 是库里已有的行，本来就属于这本书。
    """
    if not inspiration_ids or not chapter_id:
        return

    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        await conn.execute(_USED_SQL, (chapter_id, list(inspiration_ids), chapter_id))


def render_inspirations(items: list[dict]) -> str:
    """这一轮挑中 / 指定的灵感渲染成给模型看的一段；没有就返回空串（调用方据此决定插不插）。"""
    lines = []
    for item in items or ():
        name = (item.get("title") or item.get("name") or "未命名").strip()
        label = _KIND_LABEL.get(item.get("type") or "", "素材")
        content = (item.get("content") or "").strip()
        if len(content) > MAX_INSPIRATION_CHARS:
            content = f"{content[:MAX_INSPIRATION_CHARS]}…（原 {len(content)} 字符，已截断）"
        lines.append(f"- 《{name}》（{label}）：{content or '（没读到内容）'}")
    return "\n".join(lines)


def render_chapter_inspirations(items: list[dict]) -> str:
    """本章最终选用的灵感渲染给写手 / 审查看：标题、类型、场景、**写作指引**、原文。"""
    lines = []
    for item in items or ():
        title = (item.get("title") or "未命名").strip()
        cats = "、".join(CATEGORY_LABEL.get(c, c) for c in (item.get("category") or []))
        content = (item.get("content") or "").strip()
        if len(content) > MAX_INSPIRATION_CHARS:
            content = f"{content[:MAX_INSPIRATION_CHARS]}…（已截断）"
        parts = [f"- 《{title}》〔{cats or '未分类'}〕"]
        scenario = (item.get("scenario") or "").strip()
        if scenario:
            parts.append(f"  场景：{scenario}")
        digest = (item.get("digest") or "").strip()
        if digest:
            parts.append(f"  写作指引：{digest}")
        how = (item.get("how") or "").strip()
        if how:
            parts.append(f"  本章用法：{how}")
        parts.append(f"  原文：{content or '（无）'}")
        lines.append("\n".join(parts))
    return "\n".join(lines)