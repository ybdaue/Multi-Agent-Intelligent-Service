"""本章台账：writer 交完稿多报的两样 —— 这一章**用到**了哪些已有设定、**新造**了哪些东西。

在写作这一环顺手报最准也最省（它本来就知道自己用了谁、造了什么），将来改设定才查得出哪些
章节被波及。用到/提到的 → novel_chapter_ref（章节 ↔ 设定的关联表）；新造的 → 先落它自己的表
再挂一条 ref，下一章再写它就变成"已有"。reader 反着用它取档案核正文（fetch_ref_facts）。

格式：正文在前，末尾「【本章台账】」紧跟一段 JSON：
    {"refs": [{"refType": "character", "refId": "目录里的 id", "role": "key"}],
     "new": [{"refType": "item", "fields": {"name": "青锋剑", "type": "兵器"}}]}
字段一致性三处对齐、不许各自发明：JSON 的键就是 Prisma 列名；refType 必须是 RefType 九个枚举
之一（枚举列写错会整条 INSERT 回滚，所以 normalize_refs 先筛）；实体字段只认 NEW_ENTITY_SPEC。
解析不出来就给空表、不报错，为它把一章卡住不值当。

写库幂等：实体按"认身份的那一列"查了再插，ref 靠 (chapterId, refType, refId) 唯一 + ON CONFLICT
只更新 role，重跑不会插出重复。重写一章时关联整批换掉（除非这一稿没给出可用的台账，那就一行
不动），新造的实体不删 —— 实体是整本书共用的，别的章可能也挂着它。
"""
import re
import uuid
from typing import Any

from ...utils.models import parse_json_value
from .novel_information import SETTING_STATUS

# 台账的起始标记，与 writer 提示词里写的必须一致。前后允许排版小动作、也不要求独占一行
# （模型可能把 JSON 直接接在标记后面）。匹配宁可放宽：漏掉台账的后果是那段 JSON 被当成正文存库。
MARK = "【本章台账】"
_MARK = re.compile(r"[ \t>*#-]*" + re.escape(MARK) + r"[ \t*]*")

# 正文的起始标记：交稿时独占一行写在正文前面，把动笔前的分析挡在正文之外。
# 与 writer / editor 的提示词同一口径；流式层（api/novel/stream.py）也认它，
# 两边共用这两个常量，"用户看到的"与"落库的"才是同一段。
PROSE_MARK = "【正文】"
_PROSE = re.compile(r"^[ \t>*#-]*" + re.escape(PROSE_MARK) + r"[ \t*]*", re.M)

# 紧跟在标记后面的那行标题（`# 第X章 标题`）：它单独存 novel_chapter.title，正文里不留 ——
# 页面上标题栏与正文区都在，正文里再留一份就是同一句话显示两遍。落库
# （chapter_information.split_title）与流式层（api/novel/stream.py）共用这一条规则，
# 两边摘掉的必须是同一行，不然用户看到的与存进库的又对不上了。
# 行首的 # 不带缩进、行里带「章」，与 count_chapter_words 的口径一致。
TITLE_LINE = re.compile(r"^#{1,6}[ \t]*([^\n]*章[^\n]*?)[ \t]*$", re.M)

# refType → 目标表。RefType 枚举的全部九个取值，枚举列写不进去的值在这里就被筛掉。
REF_TABLES = {
    "character": "novel_character",
    "faction": "novel_faction",
    "outline": "novel_outline",
    "timeline": "novel_timeline",
    "chronicle": "novel_chronicle",
    "foreshadowing": "novel_foreshadowing",
    "item": "novel_item",
    "inspiration": "novel_inspiration",
    "world_rule": "novel_world_rule",
}

# ref 的 role：空着或认不出来一律按提及算 —— 关联本身是真的，宁可少标也不要漏挂。
ROLE_VALUES = ("mention", "key", "state")
DEFAULT_ROLE = "mention"
_ROLE_RANK = {"mention": 0, "state": 1, "key": 2}

# 能新造的七类：一章写到哪儿才第一次长出来的东西（不收大纲，开书时就定死了；不收灵感，
# 那是写作笔记，报 ref 就够了）。每类三样：
#   key            认身份的那一列，判"已有同名"与重跑幂等都按它，必须短而稳。
#   columns        模型能填的列 → 没填时的默认值；既是提示词里列的字段，也是入库的白名单。
#   chapterColumn  这一章自己填的列（值是这个章节的 id），不由模型报。
NEW_ENTITY_SPEC = {
    "character": {
        "table": "novel_character",
        "key": "name",
        "columns": {
            "name": "", "sex": "", "age": "", "birthYear": "", "deathYear": "",
            "description": "", "identity": "", "personality": "", "ability": "",
            "role": "配角",  # 与 novel_character.role 的库默认值一致，别让新角色顶着空身份
        },
    },
    "faction": {
        "table": "novel_faction",
        "key": "name",
        "columns": {"name": "", "type": "", "location": "", "description": "", "stance": ""},
    },
    "item": {
        "table": "novel_item",
        "key": "name",
        # 不收 ownerId：真外键，模型报一个不存在的持有者会当场撞约束把事务带崩。
        "columns": {"name": "", "type": "", "description": "", "status": SETTING_STATUS},
        "chapterColumn": "firstAppearanceChapterId",  # 首次登场就是这一章
    },
    "world_rule": {
        "table": "novel_world_rule",
        "key": "name",
        "columns": {"name": "", "rule": "", "status": SETTING_STATUS},
        "chapterColumn": "startChapterId",  # 从这一章起生效
    },
    "timeline": {
        "table": "novel_timeline",
        "key": "title",
        "columns": {"title": "", "year": "", "description": "", "status": SETTING_STATUS},
        "chapterColumn": "startChapterId",  # 这条线从这一章起牵出来
    },
    "chronicle": {
        "table": "novel_chronicle",
        "key": "title",
        # 编年史没有章节列，跟本章的挂钩由 novel_chapter_ref 那条 ref 表达。
        "columns": {"title": "", "year": "", "content": ""},
    },
    "foreshadowing": {
        "table": "novel_foreshadowing",
        "key": "description",
        "columns": {"description": "", "status": SETTING_STATUS},
        "chapterColumn": "plantedChapterId",  # 伏笔就埋在这一章
    },
}

# 实体目录给 writer 一份"库里已经有什么"的名单，据此分辨用已有的（refs 给 id）还是新造的。
# utils/impact.py 也拿它把类型说成人话，两处用同一份。
TYPE_LABEL = {
    "character": "人物",
    "faction": "势力",
    "item": "物品",
    "world_rule": "世界规则",
    "timeline": "时间线",
    "chronicle": "编年史",
    "outline": "大纲",
    "foreshadowing": "伏笔",
    "inspiration": "灵感",
}

CATALOG = (
    ("character", "novel_character", '"name"'),
    ("faction", "novel_faction", '"name"'),
    ("item", "novel_item", '"name"'),
    ("world_rule", "novel_world_rule", '"name"'),
    ("timeline", "novel_timeline", '"title"'),
    ("chronicle", "novel_chronicle", '"title"'),
    ("outline", "novel_outline", 'left("content", 40)'),
    ("foreshadowing", "novel_foreshadowing", 'left("description", 40)'),
    ("inspiration", "novel_inspiration", 'left("content", 40)'),
)

# 每类最多给多少条：写熟的书人物会有几百个，全塞进提示词会把真正的材料挤没了。
CATALOG_LIMIT = 100
MAX_CATALOG_CHARS = 6_000

# 每个 UNION 分支都带 ORDER BY / LIMIT，PG 要求这种子查询加括号。表名与列名全是常量，
# 没有一处是模型给的，所以可以直接拼进 SQL。
CATALOG_SQL = " UNION ALL ".join(
    f"(SELECT '{ref_type}' AS ref_type, id, {label} AS label FROM {table} "
    f'WHERE "novelId" = %s ORDER BY "createdAt" LIMIT {CATALOG_LIMIT})'
    for ref_type, table, label in CATALOG
)

# (chapterId, refType, refId) 唯一，重跑一次是 UPDATE role。refType 是枚举列，
# 必须显式转成 RefType，光给 %s 服务端不知道按哪个类型解。
REF_INSERT = (
    'INSERT INTO novel_chapter_ref (id, "chapterId", "refType", "refId", role, "createdAt") '
    'VALUES (%s, %s, %s::"RefType", %s, %s, now()) '
    'ON CONFLICT ("chapterId", "refType", "refId") DO UPDATE SET role = EXCLUDED.role'
)

# 重写这一章时整批换：旧的关联先全删，再按这一稿的台账写新的。
DELETE_REFS = 'DELETE FROM novel_chapter_ref WHERE "chapterId" = %s'

# 审查要摆到台面上的几类：大纲与世界规则已由 get_writer_context 给过，灵感没什么可核的。
FACT_TYPES = ("character", "faction", "item", "timeline", "chronicle", "foreshadowing")

# 哪些戏份摆全字段、哪些只摆一行。三种戏份都取回来：模型漏标 role 会被兜成 mention，
# 只取 key / state 的话那条就静默地不参与审查了。
FACT_FULL_ROLES = ("key", "state")

# status 是审校状态（draft / done），不是"这东西在世界里怎么样了" —— 摆出来会被读成假冲突。
FACT_SKIP_COLUMNS = ("status",)

# 单个字段、整份档案的上限：截太狠审不出东西，不封顶会把正文挤出上下文。
MAX_FACT_CELL_CHARS = 400
MAX_FACTS_CHARS = 8_000

# 正文扫名补漏：只扫名字够短的几类（大纲内容片段在正文里必撞，不扫）。
ENTITY_SCAN_TYPES = frozenset({"character", "faction", "item", "world_rule", "timeline", "chronicle"})
_MIN_NAME_LEN = 2
_MAX_NAME_LEN = 20


async def fetch_names(novel_id: str) -> list[tuple[str, str, str]]:
    """取书里已有实体的 (refType, id, name)，只限 ENTITY_SCAN_TYPES 那六类。"""
    from api.utils.db import pg_pool

    sql = (
        "SELECT 'character', id, name FROM novel_character "
        'WHERE "novelId" = %s AND name IS NOT NULL AND name != \'\' ORDER BY "createdAt" LIMIT 300'
        " UNION ALL "
        "SELECT 'faction', id, name FROM novel_faction "
        'WHERE "novelId" = %s AND name IS NOT NULL AND name != \'\' ORDER BY "createdAt" LIMIT 300'
        " UNION ALL "
        "SELECT 'item', id, name FROM novel_item "
        'WHERE "novelId" = %s AND name IS NOT NULL AND name != \'\' ORDER BY "createdAt" LIMIT 300'
        " UNION ALL "
        "SELECT 'world_rule', id, name FROM novel_world_rule "
        'WHERE "novelId" = %s AND name IS NOT NULL AND name != \'\' ORDER BY "createdAt" LIMIT 300'
        " UNION ALL "
        "SELECT 'timeline', id, title FROM novel_timeline "
        'WHERE "novelId" = %s AND title IS NOT NULL AND title != \'\' ORDER BY "createdAt" LIMIT 300'
        " UNION ALL "
        "SELECT 'chronicle', id, title FROM novel_chronicle "
        'WHERE "novelId" = %s AND title IS NOT NULL AND title != \'\' ORDER BY "createdAt" LIMIT 300'
    )
    async with pg_pool.connection() as conn:
        cur = await conn.execute(sql, (novel_id,) * 6)
        return await cur.fetchall()


def auto_complete_refs(refs, prose: str, known_rows: list[tuple[str, str, str]]) -> list[dict]:
    """从正文里扫出已有实体的名字，把台账漏报的那几条补进 refs。

    refs 可以是 None（这一稿完全没给台账），此时按 [] 算 —— 新章没有旧关联要留；
    正文里匹配到的补成 mention（最低戏份，不影响已有 ref 的 role）。
    """
    result = list(refs) if refs is not None else []
    seen = {(r["refType"], r["refId"]) for r in result}
    for ref_type, ref_id, label in known_rows:
        name = str(label or "").strip()
        if not name or len(name) < _MIN_NAME_LEN or len(name) > _MAX_NAME_LEN:
            continue
        if (ref_type, ref_id) not in seen and name in prose:
            result.append({"refType": ref_type, "refId": ref_id, "role": "mention"})
            seen.add((ref_type, ref_id))
    return result


def split_ledger(reply: str) -> tuple[str, str]:
    """回复切成 (正文, 台账文本)，切点在台账标记上。

    **标记前是空的就整段当正文、台账给空串** —— 宁可台账丢了，也不能把正文判没。
    """
    text = reply or ""
    match = _MARK.search(text)
    if not match:
        return text, ""
    prose = text[: match.start()].rstrip()
    if not prose:
        return text, ""
    return prose, text[match.end():].strip()


def split_submission(reply: str) -> tuple[str, str]:
    """模型交的整段回复 → (正文, 台账文本)。

    先按正文标记把动笔前的分析砍掉，再交给 split_ledger 切台账。标记没写就退化成
    split_ledger 的行为 —— 宁可多留一段分析进正文，也不能把正文判没。
    """
    text = reply or ""
    match = _PROSE.search(text)
    if match:
        text = text[match.end():]
    return split_ledger(text)


def parse_ledger(text: str) -> tuple[list[dict] | None, list[dict]]:
    """台账文本 → (refs, new)，一律不抛异常（容错交给 parse_json_value）。

    refs 可能是 **None**，意思是"这一稿没给出可用的关联清单"（没写、解不出来、没有 refs 键），
    write_ledger 据此别去动旧的关联；给了 `"refs": []` 是明确说不涉及任何已有设定，该换掉。
    """
    if not (text or "").strip():
        return None, []
    try:
        payload = parse_json_value(text)
    except (ValueError, TypeError):
        return None, []
    if not isinstance(payload, dict):
        return None, []

    raw_refs = payload.get("refs")
    refs = normalize_refs(raw_refs) if isinstance(raw_refs, list) else None
    return refs, normalize_new(payload.get("new"))


def _text(value: Any) -> str:
    """模型给的标量转成能进文本列的东西：数字照写，别的给空串。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _items(raw: Any) -> list:
    return raw if isinstance(raw, list) else []


def normalize_refs(raw: Any) -> list[dict]:
    """refs 洗一遍：认不出的类型、空的 refId 直接丢，同一条只留最重的那个 role（key > state > mention）。

    只留最重的：模型会把同一个人报两遍，两行只有 role 不同，留着就是重复条目。
    """
    best: dict[tuple[str, str], dict] = {}
    for item in _items(raw):
        if not isinstance(item, dict):
            continue
        ref_type = str(item.get("refType") or "").strip()
        ref_id = str(item.get("refId") or "").strip()
        if ref_type not in REF_TABLES or not ref_id:
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in ROLE_VALUES:
            role = DEFAULT_ROLE
        key = (ref_type, ref_id)
        if key not in best or _ROLE_RANK[role] > _ROLE_RANK[best[key]["role"]]:
            best[key] = {"refType": ref_type, "refId": ref_id, "role": role}
    return list(best.values())


def normalize_new(raw: Any) -> list[dict]:
    """new 洗一遍：只收能新造的几类，字段只留白名单里的，认身份那一列空着的丢掉。

    白名单是字段一致性那道闸（多写的键直接丢），NOT NULL 列漏填拿默认值补上；
    身份列空着的认不出是什么东西，留着就是每重跑一次插一行。
    """
    entries: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in _items(raw):
        if not isinstance(item, dict):
            continue
        ref_type = str(item.get("refType") or "").strip()
        spec = NEW_ENTITY_SPEC.get(ref_type)
        fields = item.get("fields")
        if spec is None or not isinstance(fields, dict):
            continue
        # 缺的、空的、类型不对的都落到默认值上。
        kept = {
            column: (_text(fields.get(column)) or default)
            for column, default in spec["columns"].items()
        }
        identity = kept[spec["key"]]
        if not identity:
            continue
        key = (ref_type, identity)
        if key in seen:
            continue
        seen.add(key)
        entries.append({"refType": ref_type, "fields": kept})
    return entries


def render_catalog(rows) -> str:
    """目录查询的结果行 → 给 writer 看的几行，按类型分块。没查到的类型不出现。"""
    grouped: dict[str, list[str]] = {}
    for ref_type, ref_id, label in rows or []:
        text = " ".join(str(label or "").split())
        grouped.setdefault(ref_type, []).append(f"- {ref_id} {text}".rstrip())

    blocks = []
    for ref_type, _table, _label in CATALOG:  # 按 CATALOG 的顺序排，跟提示词一致
        lines = grouped.get(ref_type)
        if lines:
            blocks.append(f"{TYPE_LABEL[ref_type]}（{ref_type}）：\n" + "\n".join(lines))

    text = "\n\n".join(blocks)
    if len(text) > MAX_CATALOG_CHARS:
        text = text[:MAX_CATALOG_CHARS] + "…（目录太长，只列到这里；查不到的用 fetchDB 点查）"
    return text


async def fetch_catalog(novel_id: str) -> str:
    """只取目录 —— editor 改设定时要看"库里现在有哪些"，不必捎带上一章正文那些材料。"""
    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(CATALOG_SQL, (novel_id,) * len(CATALOG))
        return render_catalog(await cur.fetchall())


def _quote(columns) -> str:
    return ", ".join(f'"{column}"' for column in columns)


async def _create_entities(conn, novel_id: str, chapter_id: str, entries: list[dict]) -> list[dict]:
    """new 里的每一样先落它自己的表，返回对应的 ref（新造的东西在这一章一定是关键戏份）。

    先拿身份列查一遍，已经有了就只把 id 带回、**不动它已有的内容**：撞名说明 writer 把"已有"
    当成了"新造"，它给的字段是凭印象编的，盖上去就是改坏一份设定。
    用"查了再插"而不是 ON CONFLICT：只有人物 / 势力 / 物品三张表有 (novelId, name) 唯一约束，
    一条 SQL 喂不了七种表；查和插在同一个事务里，一样幂等。
    """
    created = []
    for entry in entries:
        spec = NEW_ENTITY_SPEC[entry["refType"]]
        fields = entry["fields"]
        key_column = spec["key"]

        cur = await conn.execute(
            f'SELECT id FROM {spec["table"]} WHERE "novelId" = %s AND "{key_column}" = %s LIMIT 1',
            (novel_id, fields[key_column]),
        )
        row = await cur.fetchone()
        if row is not None:
            created.append({"refType": entry["refType"], "refId": row[0], "role": "key"})
            continue

        columns = list(fields)  # 键序就是 NEW_ENTITY_SPEC 里 columns 的顺序
        values = list(fields.values())
        chapter_column = spec.get("chapterColumn")
        if chapter_column:
            columns.append(chapter_column)
            values.append(chapter_id)

        placeholders = ", ".join(["%s"] * len(columns))
        sql = (
            f'INSERT INTO {spec["table"]} ("id", "novelId", {_quote(columns)}, '
            f'"createdAt", "updatedAt") VALUES (%s, %s, {placeholders}, now(), now()) '
            f"RETURNING id"
        )
        cur = await conn.execute(sql, (uuid.uuid4().hex, novel_id, *values))
        row = await cur.fetchone()
        created.append({"refType": entry["refType"], "refId": row[0], "role": "key"})
    return created


async def _live_ids(conn, novel_id: str, refs: list[dict]) -> set[str]:
    """挨类去目标表对一遍，返回真存在的 id 集合。

    模型可能报一个自己编的 id，而 novel_chapter_ref.refId 没有外键能拦（refType 决定它指向
    哪张表），不查一遍就会留下指向虚无的关联，影响分析照着它给用户报一处不存在的地方。
    """
    by_type: dict[str, list[str]] = {}
    for ref in refs:
        by_type.setdefault(ref["refType"], []).append(ref["refId"])

    found: set[str] = set()
    for ref_type, ids in by_type.items():
        cur = await conn.execute(
            f'SELECT id FROM {REF_TABLES[ref_type]} WHERE "novelId" = %s AND id = ANY(%s)',
            (novel_id, ids),
        )
        found.update(row[0] for row in await cur.fetchall())
    return found


async def write_ledger(conn, novel_id: str, chapter_id: str, refs, new_entries) -> int:
    """把这一章的台账落库，返回挂上了多少条关联。

    跑在调用方的事务里（upsert_chapter 那个），章节、新实体、关联要么一起成要么一起不成。
    chapter_id 必须是已落库的章节 id（新造的物品要把 firstAppearanceChapterId 指到它）。
    refs 传列表就整批换掉这一章的关联（重写时章节 id 不变，"这一章的关联"该恰好等于这一稿
    报的那些）；传 None 就一行不动，见 parse_ledger。
    """
    created = await _create_entities(conn, novel_id, chapter_id, new_entries or [])
    # 新造的也挂一条 ref（一定是关键戏份），跟报上来的一起去重（按 (refType, refId) 只留一条）。
    merged = normalize_refs([*(refs or []), *created])

    if refs is not None:
        await conn.execute(DELETE_REFS, (chapter_id,))
    if not merged:
        return 0

    live = await _live_ids(conn, novel_id, merged)
    written = 0
    for ref in merged:
        if ref["refId"] not in live:
            continue
        await conn.execute(
            REF_INSERT,
            (uuid.uuid4().hex, chapter_id, ref["refType"], ref["refId"], ref["role"]),
        )
        written += 1
    return written


def _clip_cell(value: Any, limit: int = MAX_FACT_CELL_CHARS) -> str:
    """档案里的一格：压成一行、超长截断。"""
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit]}…"


# 认身份的那一列里够短、能当标题使的（伏笔认整条 description，不算）。
_SHORT_KEYS = ("name", "title")
_HEADLINE_CHARS = 60


def _render_fact(ref_type: str, ref_id: str, values: dict, role: str) -> str:
    """一条档案 → 一小段。认身份的那一列提到头一行，空着的格子不写。

    role 是 mention 的只留头一行（没戏份可核，摆字段只会把正文挤出上下文），但它得在场。
    """
    spec = NEW_ENTITY_SPEC[ref_type]
    key_column = spec["key"]
    headline = _clip_cell(values.get(key_column), _HEADLINE_CHARS)
    lines = [f"【{TYPE_LABEL[ref_type]}】{headline}（本章戏份：{role}，id {ref_id}）"]
    if role not in FACT_FULL_ROLES:
        return lines[0]
    for column, value in values.items():
        text = _clip_cell(value)
        if not text or (column == key_column and key_column in _SHORT_KEYS):
            continue
        lines.append(f"  {column}：{text}")
    return "\n".join(lines)


async def fetch_ref_facts(novel_id: str, refs) -> str:
    """把台账里的 refs 指向的那些行取回来，排成一段给审稿看的档案。

    取的是**库里现在的样子**，不是 writer 凭印象写的那份 —— 要审的"冲突"正是两者之间的差。
    取不到的（编的 id、别的书的 id、已删的行）不出现也不报错，比因为一条坏 id 整轮审不成要好。
    """
    wanted: dict[str, list[str]] = {}
    roles: dict[tuple[str, str], str] = {}
    for ref in refs or []:
        if not isinstance(ref, dict):
            continue
        ref_type = str(ref.get("refType") or "").strip()
        ref_id = str(ref.get("refId") or "").strip()
        role = str(ref.get("role") or "").strip().lower()
        if ref_type not in FACT_TYPES or not ref_id or role not in ROLE_VALUES:
            continue
        wanted.setdefault(ref_type, []).append(ref_id)
        roles[(ref_type, ref_id)] = role
    if not wanted:
        return ""

    from api.utils.db import pg_pool

    blocks: list[str] = []
    async with pg_pool.connection() as conn:
        for ref_type in FACT_TYPES:  # 按固定顺序排，同一份台账每次渲染出来都一样
            ids = wanted.get(ref_type)
            if not ids:
                continue
            spec = NEW_ENTITY_SPEC[ref_type]
            # 整类一次取回来：mention 那几行取到了字段也不摆，另发一条查询不值得。
            columns = [c for c in spec["columns"] if c not in FACT_SKIP_COLUMNS]
            cur = await conn.execute(
                f'SELECT "id", {_quote(columns)} FROM {spec["table"]} '
                f'WHERE "novelId" = %s AND "id" = ANY(%s)',
                (novel_id, ids),
            )
            for row in await cur.fetchall():
                values = dict(zip(columns, row[1:]))
                blocks.append(_render_fact(ref_type, row[0], values, roles[(ref_type, row[0])]))

    text = "\n\n".join(blocks)
    if len(text) > MAX_FACTS_CHARS:
        text = text[:MAX_FACTS_CHARS] + "\n…（档案太长，只到这里）"
    return text
