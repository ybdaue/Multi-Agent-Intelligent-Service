"""本章台账：writer 交完稿多报的四样 —— 这一章**用到**了哪些已有设定、**新造**了哪些东西、
**改变**了哪些会随剧情演变的设定、**处在**哪条阶段线 / 支线上。

在写作这一环顺手报最准也最省（它本来就知道自己用了谁、造了什么、改了什么、写到了哪个阶段），将来
改设定才查得出哪些章节被波及。用到/提到的 → novel_chapter_ref（章节 ↔ 设定的关联表）；新造的 → 先落
它自己的表再挂一条 ref，下一章再写它就变成"已有"；变化的那五类（人物/势力/物品/世界规则/关系）→ 照旧
行建一版新行（旧行的 next 指向新行、新行的 firstAppearanceChapterId 钉本章），本章对旧版的 ref
重指到新版本；阶段线 / 支线 → novel_outline 的 level=phase / branch 那几行（主线由 setup 落，不在台账里）。
reader 反着用它取档案核正文（fetch_ref_facts）。

格式：正文在前，末尾「【本章台账】」紧跟一段 JSON：
    {"refs": [{"refType": "character", "refId": "目录里的 id", "role": "key"}],
     "new": [{"refType": "item", "fields": {"name": "青锋剑", "type": "兵器"}}],
     "changed": [{"refType": "character", "refId": "旧版 id", "fields": {"ability": "……"}}],
     "lines": [{"level": "branch", "id": "", "action": "open", "content": "主角误入宗门大比"}]}
字段一致性三处对齐、不许各自发明：JSON 的键就是 Prisma 列名；refType 必须是 RefType 九个枚举
之一（枚举列写错会整条 INSERT 回滚，所以 normalize_refs 先筛）；实体字段只认 NEW_ENTITY_SPEC、
变化列只认 VERSION_EDIT；lines 只认 phase / branch 两级（见 normalize_lines）。解析不出来就给空表、
不报错，为它把一章卡住不值当。

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
    "relation": "novel_relation",
}

# ref 的 role：空着或认不出来一律按提及算 —— 关联本身是真的，宁可少标也不要漏挂。
ROLE_VALUES = ("mention", "key", "state")
DEFAULT_ROLE = "mention"
_ROLE_RANK = {"mention": 0, "state": 1, "key": 2}

# 伏笔的生命周期只有两值：open 未收尾 / resolved 已收尾。这不是别的表那套审校状态
# （SETTING_STATUS 的 draft / done），而是"这个悬念收没收回" —— 由写手在台账里报（埋进 new、
# 收进 resolved），落库时改 status + resolvedChapterId。
FORESHADOW_OPEN = "open"
FORESHADOW_RESOLVED = "resolved"

# 能新造的八类：一章写到哪儿才第一次长出来的东西（不收大纲，开书时就定死了；不收灵感，
# 那是写作笔记，报 ref 就够了）。每类三样：
#   key            认身份的列，判"已有同名"与重跑幂等都按它；可以是一个列名，也可以是几个列名
#                  组成的元组（关系是"谁→谁是什么关系"三列一起才算一条）。必须短而稳。
#   columns        模型能填的列 → 没填时的默认值；既是提示词里列的字段，也是入库的白名单。
#   nameRefs       模型写的是"名字"、落库要换成真列的字段（物品持有者 owner → ownerId）：
#                  真外键不能由模型直接填 id，得先按当前版实体的名字解析（见 _create_entities）。
#   chapterColumn  这一章自己填的列（值是这个章节的 id），不由模型报。
#   writerOnly     只有写手能造（editor / setup 没有造它的材料），见 impact.py 那几处守卫。
NEW_ENTITY_SPEC = {
    "character": {
        "table": "novel_character",
        "key": "name",
        "columns": {
            "name": "", "sex": "", "age": "", "birthYear": "", "deathYear": "",
            "description": "", "identity": "", "personality": "", "ability": "",
            "role": "配角",  # 与 novel_character.role 的库默认值一致，别让新角色顶着空身份
        },
        "chapterColumn": "firstAppearanceChapterId",  # 首次登场就是这一章
    },
    "faction": {
        "table": "novel_faction",
        "key": "name",
        "columns": {"name": "", "type": "", "location": "", "description": "", "stance": ""},
        "chapterColumn": "firstAppearanceChapterId",  # 首次登场就是这一章
    },
    "item": {
        "table": "novel_item",
        "key": "name",
        # columns 只放真数据库列（fetch_ref_facts 会 SELECT 它、_insert_setting 会 INSERT 它、
        # EDIT_SPEC 由它派生）—— 持有者模型写的是**角色名**，不是列，另放 nameRefs。
        "columns": {"name": "", "type": "", "description": "", "status": SETTING_STATUS},
        # 虚拟的 name 字段 → 落库时换成真列：owner 写角色**名**（ownerId 是真外键，模型编 id 会撞
        # 约束把事务带崩）。由代码按当前版人物解析成 ownerId，解析不出就留空（物品照建）。
        "nameRefs": {"owner": "ownerId"},
        "chapterColumn": "firstAppearanceChapterId",  # 首次登场就是这一章
    },
    "world_rule": {
        "table": "novel_world_rule",
        "key": "name",
        "columns": {"name": "", "rule": "", "status": SETTING_STATUS},
        "chapterColumn": "firstAppearanceChapterId",  # 这一条从本章起生效（首次出现）
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
        "columns": {"title": "", "year": "", "content": ""},
        "chapterColumn": "startChapterId",  # 事件发生在这一章（记录类，只有起点一列）
    },
    "foreshadowing": {
        "table": "novel_foreshadowing",
        "key": "description",
        # description 认这条伏笔是什么；resolveScenario 是"打算在什么场景下收尾"，埋的时候一并写清，
        # planner 照它判本章该不该收（正文里写没写出来由写手定）。status 不由模型报，落库恒为 open。
        "columns": {"description": "", "resolveScenario": "", "status": FORESHADOW_OPEN},
        "chapterColumn": "plantedChapterId",  # 伏笔就埋在这一章
    },
    "relation": {
        "table": "novel_relation",
        # 认身份是三列组合：谁→谁是什么关系，差一列都认不出同一条。
        # 两端写角色**名**（fromName / toName），落库时由代码按当前版人物解析成 fromCharId / toCharId
        # —— 同章新建的角色还没有 id，只有名字连得上。解析不到的整条丢弃，见 _create_entities。
        "key": ("fromName", "toName", "relationType"),
        "columns": {
            "fromName": "", "toName": "", "relationType": "",
            "strength": 0, "description": "", "status": SETTING_STATUS,
        },
        # 关系不走 _create_entities 那趟 INSERT（认身份要看两个人），这一列由 _create_relations 写。
        "chapterColumn": "firstAppearanceChapterId",  # 这条关系从本章起成立
        "writerOnly": True,  # 两端角色只有写手在正文里认得出，editor / setup 造不了
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
    "relation": "人物关系",
}

# 关系认名字那两列是角色 id，摆出来得换成人名："林默→苏晚 师徒"。章节台账
# （api/novel/method.py 的 _NAME_COLUMN）也用这一份，两处共用免得漂移。
RELATION_NAME_SQL = (
    "coalesce((select name from novel_character c where c.id = novel_relation.\"fromCharId\"), '?')"
    " || '→' || "
    "coalesce((select name from novel_character c where c.id = novel_relation.\"toCharId\"), '?')"
    " || ' ' || \"relationType\""
)

CATALOG = (
    ("character", "novel_character", '"name"'),
    # 关系紧跟人物：render_catalog 按 CATALOG 顺序拼块、尾部先被 MAX_CATALOG_CHARS 截，
    # 关系放前面才不会被截掉；也符合它是人物的附属。
    ("relation", "novel_relation", f'left({RELATION_NAME_SQL}, 60)'),
    ("faction", "novel_faction", '"name"'),
    ("item", "novel_item", '"name"'),
    ("world_rule", "novel_world_rule", '"name"'),
    ("timeline", "novel_timeline", '"title"'),
    ("chronicle", "novel_chronicle", '"title"'),
    ("outline", "novel_outline", 'left("content", 40)'),
    ("foreshadowing", "novel_foreshadowing", 'left("description", 40)'),
    ("inspiration", "novel_inspiration", 'COALESCE(NULLIF("title", \'\'), left("content", 40))'),
)

# 每类最多给多少条：写熟的书人物会有几百个，全塞进提示词会把真正的材料挤没了。
CATALOG_LIMIT = 100
MAX_CATALOG_CHARS = 6_000

# 未收尾的伏笔清单：planner 必须读到它们才判得出本章该收哪些。条数封顶，跟目录一个量级，
# 免得悬着的伏笔多了把材料挤没。
OPEN_FORESHADOW_LIMIT = 100

# 本章涉及人物的现有关系：条数封顶，跟目录一个量级，免得关系网大了把材料挤没。
RELATION_LIMIT = 100

# 会随剧情演变的五类：每变一次新建一版，链尾才是"当前版"；其余类别是记录 / 生命周期，值不变。
VERSION_TYPES = ("character", "faction", "item", "world_rule", "relation")

# 链尾判定：next 为空的那一行就是"当前版"（旧行的 next 指向它变成的那一行；没有谁再指过来，
# 就是链尾）。目录 / 扫名 / editor 定位都靠它，免得同名多版一起进提示词、模型挑错版本。
# outer 是外层查询里引这张表的名字或别名：谓词直接引外层那一行，得用外层实际叫的名字。
_TAIL_SQL = '{outer}."next" IS NULL'


def tail_filter(ref_type: str, table: str, outer: str = "") -> str:
    """该类型若是会变值的，返回"只取当前版（链尾）"的 SQL 谓词（带前导 AND）；记录类返回空串。

    outer 传外层 FROM 里那张表的名字或别名 —— 外层起了别名（如 `FROM novel_world_rule r`）
    就必须传别名，否则引用指不回外层那一行。不传按表名算。table 参数留着是为了调用点口径一致
    （谓词本身引的是外层的 next，不再 JOIN 那张表）。
    """
    if ref_type not in VERSION_TYPES:
        return ""
    return f' AND {_TAIL_SQL.format(table=table, outer=outer or table)}'

# 建新版本行时照搬旧行的列（内容全搬，免得丢 ownerId 这类不常改的列）。firstAppearanceChapterId
# **不在其中**：新版本行是"这一版出现在哪一章"，由建行时自填本章，不从旧行搬。
VERSION_COPY = {
    "character": ("name", "sex", "age", "birthYear", "deathYear", "description",
                  "identity", "personality", "ability", "role"),
    "faction": ("name", "type", "location", "description", "stance"),
    "item": ("name", "type", "description", "status", "ownerId"),
    "world_rule": ("name", "rule", "status"),
    "relation": ("fromCharId", "toCharId", "relationType", "strength", "description", "status"),
}

# changed 允许覆盖的列：身份列不许动（关系的两端 fromCharId / toCharId 指向谁就是跟谁的关系，
# 不是内容）。人物 / 势力 / 物品 / 世界规则照 NEW_ENTITY_SPEC 的字段白名单（status 在里面），
# nameRefs 那几个虚拟字段（物品的 owner）也要认 —— 它们随后由 _apply_changes 解析成真列。
VERSION_EDIT = {
    ref_type: tuple(spec["columns"]) + tuple(spec.get("nameRefs") or {})
    for ref_type, spec in NEW_ENTITY_SPEC.items()
    if ref_type in VERSION_TYPES
}
VERSION_EDIT["relation"] = ("relationType", "strength", "description")

# 每个 UNION 分支都带 ORDER BY / LIMIT，PG 要求这种子查询加括号。表名与列名全是常量，
# 没有一处是模型给的，所以可以直接拼进 SQL。会变值的那几类只列"当前版"（链尾）。
CATALOG_SQL = " UNION ALL ".join(
    f"(SELECT '{ref_type}' AS ref_type, id, {label} AS label FROM {table} "
    f'WHERE "novelId" = %s' + tail_filter(ref_type, table)
    + f' ORDER BY "createdAt" LIMIT {CATALOG_LIMIT})'
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
# 大纲 ref 不在其中 —— 那是由 card 代码生成、写口在 write_outline_refs，别让模型报的 refs 把它冲掉。
DELETE_REFS = 'DELETE FROM novel_chapter_ref WHERE "chapterId" = %s AND "refType" <> \'outline\''

# 换这一章的大纲 ref：只在写新章 / 重写那一章（给了 card 的 outline ref）时跑，改稿路径不碰。
DELETE_OUTLINE_REFS = (
    'DELETE FROM novel_chapter_ref WHERE "chapterId" = %s AND "refType" = \'outline\''
)

# 收尾伏笔：本章报的 id 里，属于这本书、且当前还开着（status=open）的，置为已收尾并记下回收章。
# 带 status=open 守卫：重跑同一章不会把已经收好的又翻一遍、也不会改掉别章记的首收章；别的书 /
# 编出来的 id / 已经收过的，一律 0 行，无事发生。
RESOLVE_FORESHADOW_SQL = (
    'UPDATE novel_foreshadowing SET status = %s, "resolvedChapterId" = %s, "updatedAt" = now() '
    'WHERE "novelId" = %s AND id = ANY(%s) AND status = %s'
)

# 台账里 lines 只报这两级：主线（main）由 setup 落好，不由写手新报。
LINE_LEVELS = ("phase", "branch")
LINE_ACTIONS = ("open", "continue", "close")

# 新开一条线：startChapterId 钉在这一章，order 用章节序号排（同一章报的多条按报的顺序）。
# parentId 表达包含关系（阶段线挂主线、支线挂阶段线），没有父给 NULL —— 空串会撞外键。
# 主线由 setup 落（level=main），这里只插 phase / branch。status 走设定那套 draft。
LINE_INSERT = (
    'INSERT INTO novel_outline (id, "novelId", level, status, "order", content, '
    '"parentId", "startChapterId", "createdAt", "updatedAt") '
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())"
)

# 收尾一条线：置 completed = true，之后 get_writer_context 不再把它算作"生效中"。
# 只认 phase / branch —— 写手若把主线的 id 报进来，别让它把 setup 落的主线收掉。
# 收尾章是哪一章不在这里记：那一章会为这条线发一条 outline ref（见 write_outline_refs）。
LINE_CLOSE = (
    'UPDATE novel_outline SET completed = true, "updatedAt" = now() '
    'WHERE id = %s AND "novelId" = %s AND level IN (\'phase\', \'branch\')'
)

# 阶段线收尾时，把它名下仍开着的支线一并收尾：阶段线都结束了，底下不该还挂着一条"生效中"的
# 支线让下一章的 planner 判错。只收 parentId 指这条阶段线、且还没收尾的支线。
LINE_CLOSE_CHILDREN = (
    'UPDATE novel_outline SET completed = true, "updatedAt" = now() '
    'WHERE "novelId" = %s AND "parentId" = %s AND level = \'branch\' AND NOT "completed"'
)

# 沿用一条线时顺手把内容刷成最新口径（写手可能把这一段的说法写细了）。同样只认 phase / branch。
LINE_UPDATE_CONTENT = (
    'UPDATE novel_outline SET content = %s, "updatedAt" = now() '
    'WHERE id = %s AND "novelId" = %s AND level IN (\'phase\', \'branch\')'
)

# 重写这一章时幂等：先把"从这一章起头"的 phase / branch 撤掉，再按新台账重挂。
# 只删 startChapterId = 这一章的，不动 setup 落的主线（level=main）和别章起的线。
DELETE_STARTED_LINES = (
    'DELETE FROM novel_outline WHERE "novelId" = %s AND "startChapterId" = %s '
    "AND level IN ('phase', 'branch')"
)

# 审查要摆到台面上的几类：大纲与世界规则已由 get_writer_context 给过，灵感没什么可核的，
# 关系（relation）也不审 —— 它只进台账供反查，不摆给 reader 核正文。
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


# 扫名要用的"认名字那一列"：正文扫名与 fetch_ref_names 共用（都只在 ENTITY_SCAN_TYPES 里查）。
_SCAN_NAME = {
    "character": ("novel_character", '"name"'),
    "faction": ("novel_faction", '"name"'),
    "item": ("novel_item", '"name"'),
    "world_rule": ("novel_world_rule", '"name"'),
    "timeline": ("novel_timeline", '"title"'),
    "chronicle": ("novel_chronicle", '"title"'),
}


async def fetch_names(novel_id: str) -> list[tuple[str, str, str]]:
    """取书里已有实体的 (refType, id, name)，只限 ENTITY_SCAN_TYPES 那六类。

    会变值的那几类只给**当前版**（链尾）：同名多版一起给会把 writer 引到错版本上，也会把
    LIMIT 300 占满、真的实体被顶掉。timeline / chronicle 是记录类，没有版本。
    """
    from api.utils.db import pg_pool

    branches = []
    for ref_type in ENTITY_SCAN_TYPES:
        table, name_col = _SCAN_NAME[ref_type]
        branches.append(
            f"(SELECT '{ref_type}', id, {name_col} FROM {table} "
            f'WHERE "novelId" = %s AND {name_col} IS NOT NULL AND {name_col} != \'\''
            + tail_filter(ref_type, table)
            + f' ORDER BY "createdAt" LIMIT 300)'
        )
    sql = " UNION ALL ".join(branches)
    async with pg_pool.connection() as conn:
        cur = await conn.execute(sql, (novel_id,) * len(branches))
        return await cur.fetchall()


async def fetch_ref_names(novel_id: str, refs) -> set[tuple[str, str]]:
    """这一章已经绑定的设定，各自的 (refType, 名字)。扫名据此跳过同名 —— 已有的（可能绑的是旧版）
    优先，扫名只补本章新出现的，不给同一个名字再补出第二版。

    **不加链尾谓词**：旧版那一行的名字正是要挡住扫名的那批，链尾过滤会把它漏掉。
    """
    wanted: dict[str, list[str]] = {}
    for ref in refs or []:
        if not isinstance(ref, dict):
            continue
        ref_type = str(ref.get("refType") or "").strip()
        ref_id = str(ref.get("refId") or "").strip()
        if ref_type in ENTITY_SCAN_TYPES and ref_id:
            wanted.setdefault(ref_type, []).append(ref_id)
    if not wanted:
        return set()

    from api.utils.db import pg_pool

    names: set[tuple[str, str]] = set()
    async with pg_pool.connection() as conn:
        for ref_type, ids in wanted.items():
            table, name_col = _SCAN_NAME[ref_type]
            cur = await conn.execute(
                f'SELECT {name_col} FROM {table} WHERE "novelId" = %s AND id = ANY(%s)',
                (novel_id, ids),
            )
            for (label,) in await cur.fetchall():
                text = str(label or "").strip()
                if text:
                    names.add((ref_type, text))
    return names


def auto_complete_refs(refs, prose: str, known_rows: list[tuple[str, str, str]],
                       covered: set[tuple[str, str]] | None = None) -> list[dict]:
    """从正文里扫出已有实体的名字，把台账漏报的那几条补进 refs。

    refs 可以是 None（这一稿完全没给台账），此时按 [] 算 —— 新章没有旧关联要留；
    正文里匹配到的补成 mention（最低戏份，不影响已有 ref 的 role）。
    covered 是这一章已绑定的 (refType, 名字)：命中的不再补 —— 已有的（可能绑的是旧版的）优先，
    扫名只补本章新出现的。
    """
    result = list(refs) if refs is not None else []
    seen = {(r["refType"], r["refId"]) for r in result}
    covered = covered or set()
    for ref_type, ref_id, label in known_rows:
        name = str(label or "").strip()
        if not name or len(name) < _MIN_NAME_LEN or len(name) > _MAX_NAME_LEN:
            continue
        if (ref_type, name) in covered:
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


def parse_ledger(text: str) -> tuple[list[dict] | None, list[dict], list[dict], list[dict], list[str]]:
    """台账文本 → (refs, new, changed, lines, resolved)，一律不抛异常（容错交给 parse_json_value）。

    refs 可能是 **None**，意思是"这一稿没给出可用的关联清单"（没写、解不出来、没有 refs 键），
    write_ledger 据此别去动旧的关联；给了 `"refs": []` 是明确说不涉及任何已有设定，该换掉。
    changed 是本章**实际发生的变化**（会变值那五类），建版本行用；没报就是 []。
    lines 是这一章所处的阶段线 / 支线，没报就是 [] —— 与 refs 的 None 不同，[] 表示这一章
    不动大纲那一块（别把旧的线删了）。resolved 是本章**收尾掉的伏笔 id**，没报就是 []。
    """
    if not (text or "").strip():
        return None, [], [], [], []
    try:
        payload = parse_json_value(text)
    except (ValueError, TypeError):
        return None, [], [], [], []
    if not isinstance(payload, dict):
        return None, [], [], [], []

    raw_refs = payload.get("refs")
    refs = normalize_refs(raw_refs) if isinstance(raw_refs, list) else None
    return (
        refs,
        normalize_new(payload.get("new")),
        normalize_changed(payload.get("changed")),
        normalize_lines(payload.get("lines")),
        normalize_resolved(payload.get("resolved")),
    )


# 改动严重程度：L1 纯润色 / L2 局部事实 / L3 结构性。写死这三值，别的一律当"没分级"。
GRADES = ("L1", "L2", "L3")


def parse_grade(text: str) -> str:
    """从台账 JSON 里取 grade（L1/L2/L3），没有 / 认不出 / 解析失败一律给空串（= 没分级 → 全量审）。

    口径同 parse_ledger：绝不抛异常，一个判词解析不出来不该把整章卡住。
    """
    if not (text or "").strip():
        return ""
    try:
        payload = parse_json_value(text)
    except (ValueError, TypeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    grade = str(payload.get("grade") or "").strip().upper()
    return grade if grade in GRADES else ""


def _text(value: Any) -> str:
    """模型给的标量转成能进文本列的东西：数字照写，别的给空串。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _as_int(value: Any, default: int = 0) -> int | None:
    """模型给的值转成能进 INT 列的数：数字照收、数字串解成数，解不出给 default（None 表示丢弃）。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


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
    """new 洗一遍：只收能新造的几类，字段只留白名单里的，认身份那几列空着的丢掉。

    白名单是字段一致性那道闸（多写的键直接丢），NOT NULL 列漏填拿默认值补上；
    认身份的列空着的认不出是什么东西，留着就是每重跑一次插一行。认身份可以是一列（spec["key"]）
    也可以是几列组成的元组（关系：fromName / toName / relationType 三列齐全才算一条）。
    """
    entries: list[dict] = []
    seen: set[tuple] = set()
    for item in _items(raw):
        if not isinstance(item, dict):
            continue
        ref_type = str(item.get("refType") or "").strip()
        spec = NEW_ENTITY_SPEC.get(ref_type)
        fields = item.get("fields")
        if spec is None or not isinstance(fields, dict):
            continue
        # 白名单 = 真列 + nameRefs 那几个虚拟字段（物品的 owner 写的是角色名，落库才换成 ownerId）。
        allowed = {**spec["columns"], **{field: "" for field in (spec.get("nameRefs") or {})}}
        # 缺的、空的、类型不对的都落到默认值上。
        kept = {
            column: (_text(fields.get(column)) or default)
            for column, default in allowed.items()
        }
        keys = spec["key"]
        if isinstance(keys, tuple):
            identity = tuple(kept.get(column) for column in keys)
            if any(not part for part in identity):
                continue
        else:
            identity = kept.get(keys)
            if not identity:
                continue
        dedup = (ref_type, identity)
        if dedup in seen:
            continue
        seen.add(dedup)
        entries.append({"refType": ref_type, "fields": kept})
    return entries


def normalize_changed(raw: Any) -> list[dict]:
    """changed 洗一遍：只收会变值那五类、refId 非空，fields 只留该类型允许覆盖的列。

    与 normalize_new 的区别：new 是"造一样新东西"（字段全要），changed 是"改一样已有设定的某几列"
    （只填变的列，没填的列照旧行搬）。fields 里空值照收（= 清空那一列）；一条也没有变动的列就丢掉
    —— 不填 fields 的 changed 是句空话，落库只会白建一版。
    """
    changes: list[dict] = []
    for item in _items(raw):
        if not isinstance(item, dict):
            continue
        ref_type = str(item.get("refType") or "").strip()
        ref_id = str(item.get("refId") or "").strip()
        fields = item.get("fields")
        allowed = VERSION_EDIT.get(ref_type)
        if not ref_id or allowed is None or not isinstance(fields, dict):
            continue
        # 空值照收（清空），但没给的列不落 —— 照旧行搬。
        kept = {column: _text(fields.get(column)) for column in allowed if column in fields}
        if not kept:
            continue
        changes.append({"refType": ref_type, "refId": ref_id, "fields": kept})
    return changes


def normalize_lines(raw: Any) -> list[dict]:
    """lines 洗一遍：只认 phase / branch、action 只认 open / continue / close，其余整条丢掉。

    - open：新开一条，必须有内容（没有内容就是一条空线，认不出是什么）；id 一律清零。
    - continue：沿用在写的那一条，必须有 id（没有就指不到目标），可带新版内容。
    - close：收尾已有的一条，必须有 id，content 不用给。
    """
    lines: list[dict] = []
    for item in _items(raw):
        if not isinstance(item, dict):
            continue
        level = str(item.get("level") or "").strip()
        action = str(item.get("action") or "").strip()
        if level not in LINE_LEVELS or action not in LINE_ACTIONS:
            continue
        line_id = str(item.get("id") or "").strip()
        content = _text(item.get("content"))
        if action == "open":
            if not content:
                continue
            line_id = ""
        elif not line_id:
            continue
        lines.append({"level": level, "action": action, "id": line_id, "content": content})
    return lines


def normalize_resolved(raw: Any) -> list[str]:
    """resolved 洗一遍：只留非空的 id 字符串，去重（模型可能把同一条报两遍）。

    合法性（是不是这本书的、是不是还开着）由落库那步核（_resolve_foreshadowings），这里只把形状
    理干净 —— 报错一个坏 id 不该把整章落库带崩，那一步带着 status=open 的守卫，认不出就无事发生。
    """
    ids: list[str] = []
    seen: set[str] = set()
    for item in _items(raw):
        text = item.strip() if isinstance(item, str) else ""
        if text and text not in seen:
            seen.add(text)
            ids.append(text)
    return ids


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


# 未收尾的伏笔：埋在哪一章的序号一并带出来（plantedChapterId 是章节 id，"第几章"才有用；埋章
# 已删就留 NULL）。planner 拿这份清单 + 每条的 resolveScenario 判本章剧情是否走到了该收的时候。
_OPEN_FORESHADOW_SQL = (
    'SELECT f.id, f.description, f."resolveScenario", c."order" '
    'FROM novel_foreshadowing f '
    'LEFT JOIN novel_chapter c ON c.id = f."plantedChapterId" '
    'WHERE f."novelId" = %s AND f.status = %s '
    'ORDER BY f."createdAt" LIMIT %s'
)


async def fetch_open_foreshadowings(novel_id: str) -> list[dict]:
    """这本书还没收尾的伏笔 → [{id, description, resolveScenario, planted_order}]，给 planner 判收尾用。

    只取 status=open 的：收过的伏笔不必再摆出来（免得 planner 又把它挑一遍）。
    """
    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            _OPEN_FORESHADOW_SQL, (novel_id, FORESHADOW_OPEN, OPEN_FORESHADOW_LIMIT)
        )
        rows = await cur.fetchall()
    return [
        {
            "id": ref_id,
            "description": description or "",
            "resolveScenario": resolve_scenario or "",
            "planted_order": planted_order,
        }
        for ref_id, description, resolve_scenario, planted_order in rows
    ]


# 本章相关人物的现有关系：谁 → 谁是什么关系。两端换成角色名（fromCharId / toCharId 是人物 id，
# 摆出来模型读不出是谁）。只取当前版（链尾）—— 关系会变，同名多版一起给会把写手引到旧关系上。
# 命中口径：两端沾到本章任一个人物，或本章直接 ref 了这条关系。
_SCOPE_RELATION_SQL = (
    'SELECT r.id, fc.name, tc.name, r."relationType", r.strength, r.description '
    'FROM novel_relation r '
    'LEFT JOIN novel_character fc ON fc.id = r."fromCharId" '
    'LEFT JOIN novel_character tc ON tc.id = r."toCharId" '
    'WHERE r."novelId" = %s AND (r."fromCharId" = ANY(%s) OR r."toCharId" = ANY(%s) '
    'OR r.id = ANY(%s))' + tail_filter("relation", "novel_relation", outer="r")
    + ' ORDER BY r."createdAt" LIMIT %s'
)


async def fetch_relations(novel_id: str, char_ids, relation_ids=None) -> list[dict]:
    """本章相关人物之间/身上的现有关系 → [{id, fromName, toName, relationType, strength, description}]。

    只取 status 不分（关系没有收尾状态那套）；只取**当前版**（链尾）。char_ids 与 relation_ids
    都空就给空表 —— 没有相关人物就没有关系可摆。给 planner 与写手同一份，写的时候照它保持一致。
    """
    char_ids = [str(c) for c in (char_ids or []) if c]
    relation_ids = [str(r) for r in (relation_ids or []) if r]
    if not char_ids and not relation_ids:
        return []

    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            _SCOPE_RELATION_SQL,
            (novel_id, char_ids, char_ids, relation_ids, RELATION_LIMIT),
        )
        rows = await cur.fetchall()
    return [
        {
            "id": ref_id,
            "fromName": from_name or "？",
            "toName": to_name or "？",
            "relationType": relation_type or "",
            "strength": strength,
            "description": description or "",
        }
        for ref_id, from_name, to_name, relation_type, strength, description in rows
    ]


# 取"序号严格小于 order 的最近一章"的台账 refs：给 writer.prepare / reader.gather 用 ——
# 动笔与审稿都还没有本章的台账，能拿的只有上一章那份（它用到哪些设定，就是新一轮要接住的）。
# 中间删过章会有空洞，所以取 max(order) < 目标的那一章，不写死 order-1。
PREV_REFS_SQL = (
    'SELECT r."refType", r."refId", r.role FROM novel_chapter_ref r '
    'JOIN novel_chapter c ON c.id = r."chapterId" '
    'WHERE c."novelId" = %s AND c."order" = ('
    'SELECT MAX("order") FROM novel_chapter WHERE "novelId" = %s AND "order" < %s)'
)


async def fetch_chapter_refs(novel_id: str, order: int) -> list[dict]:
    """取目标章前面最近那一章的台账 refs（[{refType, refId, role}]），没有就给空表。

    上一章没有、或它没报过台账时返回 []，调用方喂给 fetch_ref_facts 自然得到空档案。
    """
    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(PREV_REFS_SQL, (novel_id, novel_id, order))
        rows = await cur.fetchall()
    return [{"refType": ref_type, "refId": ref_id, "role": role} for ref_type, ref_id, role in rows]


async def fetch_chapter_refs_by_id(chapter_id: str) -> list[dict]:
    """取**这一章自己**的台账 refs（[{refType, refId, role}]），没有就给空表。

    与 fetch_chapter_refs 不同：那个取的是上一章的，这个是本章的 —— 人工改稿要拿"这一章上一版
    记过的台账"跟改后稿比对（见 nodes/editor/manual.py）。入账顺序取，接近正文里的出场顺序。
    novel_chapter_ref 上没有 novelId 列（chapterId 本身就全局唯一），所以只按 chapterId 查。
    """
    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT "refType", "refId", role FROM novel_chapter_ref '
            'WHERE "chapterId" = %s ORDER BY "createdAt", id',
            (chapter_id,),
        )
        rows = await cur.fetchall()
    return [{"refType": ref_type, "refId": ref_id, "role": role} for ref_type, ref_id, role in rows]


def _quote(columns) -> str:
    return ", ".join(f'"{column}"' for column in columns)


async def _create_entities(conn, novel_id: str, chapter_id: str, entries: list[dict]) -> list[dict]:
    """new 里的每一样先落它自己的表，返回对应的 ref（新造的东西在这一章一定是关键戏份）。

    先拿身份列查一遍，已经有了就只把 id 带回、**不动它已有的内容**：撞名说明 writer 把"已有"
    当成了"新造"，它给的字段是凭印象编的，盖上去就是改坏一份设定。
    用"查了再插"而不是 ON CONFLICT：只有人物 / 势力 / 物品三张表有 (novelId, name) 唯一约束，
    一条 SQL 喂不了八种表；查和插在同一个事务里，一样幂等。

    关系另走一趟（见 _create_relations）：它认身份要看**两个人**，两端又写的是角色名，得先解析成
    id —— 所以先造完别的（顺带把本批人物名 → id 记下），再拿这张表 + 库里当前版人物解析两端。
    物品的持有者（nameRefs 的 owner）同理：写的是角色名、落库前解析成 ownerId（解析不出就留空）。
    """
    created = []
    char_ids: dict[str, str] = {}   # 本批人物的名字 → id（新建的与撞名命中的都在内），供关系 / 持有者解析
    relations: list[dict] = []
    # 人物先造：物品的 owner 可能正是本章新登场的角色，先集齐 name → id 才解析得动。
    ordered = [e for e in entries if e["refType"] == "character"]
    ordered += [e for e in entries if e["refType"] != "character"]
    for entry in ordered:
        if entry["refType"] == "relation":
            relations.append(entry)
            continue
        spec = NEW_ENTITY_SPEC[entry["refType"]]
        fields = entry["fields"]
        key_column = spec["key"]

        cur = await conn.execute(
            f'SELECT id FROM {spec["table"]} WHERE "novelId" = %s AND "{key_column}" = %s LIMIT 1',
            (novel_id, fields[key_column]),
        )
        row = await cur.fetchone()
        if row is not None:
            if entry["refType"] == "character":
                char_ids[fields["name"]] = row[0]
            created.append({"refType": entry["refType"], "refId": row[0], "role": "key"})
            continue

        # nameRefs（物品的 owner）写的是角色名：落库前换成真列（ownerId）；解析不出就留空，物品照建。
        for field, column in (spec.get("nameRefs") or {}).items():
            char_name = fields.pop(field, "")
            if char_name:
                char_id = await _resolve_character(conn, novel_id, char_name, char_ids)
                if char_id:
                    fields[column] = char_id

        columns = list(fields)  # 键序就是 NEW_ENTITY_SPEC 里 columns 的顺序
        values = list(fields.values())
        # 章节列（firstAppearanceChapterId / startChapterId / plantedChapterId）由代码填本章，不由模型报。
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
        if entry["refType"] == "character":
            char_ids[fields["name"]] = row[0]
        created.append({"refType": entry["refType"], "refId": row[0], "role": "key"})
    created.extend(await _create_relations(conn, novel_id, chapter_id, relations, char_ids))
    return created


async def _resolve_character(conn, novel_id: str, name: str, char_ids: dict[str, str]) -> str:
    """角色名 → 人物 id：先看本批（同章新建 / 命中的都在），再查库里**当前版**（同名多版取链尾）。

    实在解析不出（库里、本批都没有这个人）给空串 —— 造不出指向不存在的人的关系。
    """
    name = str(name or "").strip()
    if not name:
        return ""
    if name in char_ids:
        return char_ids[name]
    cur = await conn.execute(
        'SELECT id FROM novel_character WHERE "novelId" = %s AND "name" = %s'
        + tail_filter("character", "novel_character") + ' ORDER BY "createdAt" DESC LIMIT 1',
        (novel_id, name),
    )
    row = await cur.fetchone()
    if row is None:
        return ""
    char_ids[name] = row[0]
    return row[0]


async def _create_relations(conn, novel_id: str, chapter_id: str, entries: list[dict],
                            char_ids: dict[str, str]) -> list[dict]:
    """关系 new：两端角色名解析成 id 再落库，返回对应的 ref。

    两端任一解析不出、或解析成同一个人（自己跟自己不算关系）→ 整条丢弃并报一行计数。已有同样的
    **当前版**关系（两端 + relationType 都相同）就不重复插，复用那一行。strength 取整（模型给的不是
    数字就 0），status 照 spec 默认。关系是会变值的类型，新造的这行就是它第一版：
    firstAppearanceChapterId = 本章（这一版从这一章起成立）。
    """
    created = []
    dropped = 0
    for entry in entries:
        fields = entry["fields"]
        from_id = await _resolve_character(conn, novel_id, fields["fromName"], char_ids)
        to_id = await _resolve_character(conn, novel_id, fields["toName"], char_ids)
        if not from_id or not to_id or from_id == to_id:
            dropped += 1
            continue

        cur = await conn.execute(
            'SELECT id FROM novel_relation WHERE "novelId" = %s AND "fromCharId" = %s '
            'AND "toCharId" = %s AND "relationType" = %s'
            + tail_filter("relation", "novel_relation") + ' LIMIT 1',
            (novel_id, from_id, to_id, fields["relationType"]),
        )
        row = await cur.fetchone()
        if row is not None:
            created.append({"refType": "relation", "refId": row[0], "role": "key"})
            continue

        columns = ["fromCharId", "toCharId", "relationType", "strength", "description",
                   "status", "firstAppearanceChapterId"]
        values = [
            from_id, to_id, fields["relationType"], _as_int(fields.get("strength"), 0),
            fields["description"], fields["status"], chapter_id,
        ]
        placeholders = ", ".join(["%s"] * len(columns))
        cur = await conn.execute(
            f'INSERT INTO novel_relation ("id", "novelId", {_quote(columns)}, '
            f'"createdAt", "updatedAt") VALUES (%s, %s, {placeholders}, now(), now()) '
            f"RETURNING id",
            (uuid.uuid4().hex, novel_id, *values),
        )
        row = await cur.fetchone()
        created.append({"refType": "relation", "refId": row[0], "role": "key"})

    if dropped:
        print(f"[ledger] {dropped} 条关系的两端角色对不上库里的人物，已丢弃", flush=True)
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


async def write_version_row(conn, novel_id: str, ref_type: str, old_id: str, fields: dict,
                            chapter_id: str | None) -> str | None:
    """给一条会变值的设定记一版新行：照旧行搬全部内容 + 覆盖 fields，旧行的 next 指向新行
    （新行即链尾），返回新行 id；旧行查不到（坏 id / 别的书）返回 None。

    版本链只在这一处生长 —— writer 报 changed、editor 改设定都走它。能覆盖的列是 VERSION_EDIT
    白名单里的（身份列不许动，其余照旧行搬）；chapter_id 是这一版从哪一章起出现（editor 改的设定
    不挂在哪一章上，传 None）。物品的 owner 写的是角色名，落库前解析成 ownerId；关系的 strength
    是 INT 列，模型给空串 / 非数字时丢掉那一列照旧行搬（别拿它去 INSERT 把事务带崩）。
    """
    table = REF_TABLES[ref_type]
    copy_columns = VERSION_COPY[ref_type]

    cur = await conn.execute(
        f'SELECT {_quote(copy_columns)} FROM {table} WHERE "novelId" = %s AND id = %s',
        (novel_id, old_id),
    )
    row = await cur.fetchone()
    if row is None:
        return None

    values = dict(zip(copy_columns, row))
    fields = dict(fields)
    # 物品的 owner 写的是角色名：解析成 ownerId 再覆盖；留空 = 没有持有者；解析不出就不动
    # （照旧行搬）。ownerId 本就在 copy_columns 里，values.update 后即生效。
    if ref_type == "item" and "owner" in fields:
        owner_name = fields.pop("owner")
        if not owner_name:
            fields["ownerId"] = None
        else:
            owner_id = await _resolve_character(conn, novel_id, owner_name, {})
            if owner_id:
                fields["ownerId"] = owner_id
    if ref_type == "relation" and "strength" in fields:
        parsed = _as_int(fields["strength"], None)
        if parsed is None:
            fields.pop("strength")
        else:
            fields["strength"] = parsed
    values.update(fields)  # 白名单列覆盖，其余照旧行
    # 新版本行的 firstAppearanceChapterId = chapter_id（这一版从这一章起出现）；next 留空 = 链尾。
    columns = list(copy_columns) + ["firstAppearanceChapterId"]
    params = [values[column] for column in copy_columns] + [chapter_id]
    placeholders = ", ".join(["%s"] * len(columns))
    new_id = uuid.uuid4().hex
    await conn.execute(
        f'INSERT INTO {table} ("id", "novelId", {_quote(columns)}, "createdAt", "updatedAt") '
        f"VALUES (%s, %s, {placeholders}, now(), now())",
        (new_id, novel_id, *params),
    )
    # 旧行的 next 指向新行：从此链尾是这一版，旧行不再是"当前版"。
    await conn.execute(
        f'UPDATE {table} SET "next" = %s WHERE "novelId" = %s AND id = %s',
        (new_id, novel_id, old_id),
    )
    return new_id


async def _apply_changes(conn, novel_id: str, chapter_id: str, changes: list[dict]) -> dict[tuple[str, str], str]:
    """changed 里的每一条都记一版新行（见 write_version_row），返回 {(refType, 旧id): 新id} 供重指 ref 用。

    旧行查不到（坏 id / 别的书）就跳过 —— 一条坏 id 不该把整章落库带崩。
    """
    remap: dict[tuple[str, str], str] = {}
    for change in changes:
        ref_type = change["refType"]
        old_id = change["refId"]
        new_id = await write_version_row(
            conn, novel_id, ref_type, old_id, change["fields"], chapter_id
        )
        if new_id is not None:
            remap[(ref_type, old_id)] = new_id
    return remap


async def _resolve_foreshadowings(conn, novel_id: str, chapter_id: str, ids: list[str]) -> int:
    """把本章报的伏笔 id 里还开着的那几条置为已收尾（status=resolved + 记回收章）。

    这一步就是"由写手控制伏笔状态更新"的落点：谁收的、收在哪一章，全照台账报的来。带
    status=open 守卫，别的书 / 编的 id / 已收过的都改不到，重跑也幂等。返回真改了几条。
    """
    if not ids:
        return 0
    cur = await conn.execute(
        RESOLVE_FORESHADOW_SQL,
        (FORESHADOW_RESOLVED, chapter_id, novel_id, ids, FORESHADOW_OPEN),
    )
    return cur.rowcount or 0


def _repoint(refs: list[dict], remap: dict[tuple[str, str], str]) -> list[dict]:
    """把本章 refs 里指向旧版的关联重指到新版本行上；changed 的那条若不在 refs 里，补一条 state。

    重指是必须的：旧版行仍在库里（旧行的 next 已指向新行，它不再是链尾），ref 还指旧版的话，reader 审这一章拿到的
    是改动前的档案，等于没改。
    """
    if not remap:
        return list(refs)
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        new_id = remap.get((ref["refType"], ref["refId"]))
        if new_id is not None:
            ref = {**ref, "refId": new_id}
        result.append(ref)
        seen.add((ref["refType"], ref["refId"]))
    for (ref_type, _old_id), new_id in remap.items():
        if (ref_type, new_id) not in seen:
            result.append({"refType": ref_type, "refId": new_id, "role": "state"})
    return result


async def write_ledger(conn, novel_id: str, chapter_id: str, refs, new_entries,
                       changed_entries=None, resolved=None) -> int:
    """把这一章的台账落库，返回挂上了多少条关联。

    跑在调用方的事务里（upsert_chapter 那个），章节、版本行、新实体、关联要么一起成要么一起不成。
    chapter_id 必须是已落库的章节 id（新造 / 改动出的设定要把它的章节列指到它）。
    refs 传列表就整批换掉这一章的关联（重写时章节 id 不变，"这一章的关联"该恰好等于这一稿
    报的那些）；传 None 就一行不动，见 parse_ledger。
    changed 是本章实际发生的设定变化：先在 refs 之前建版本行（旧行照搬 + 改动列覆盖），再把
    本章对旧版的 ref 重指到新版本行。refs is None（这一稿没交台账）时不建版本行、不动旧关联。
    resolved 是本章收尾掉的伏笔 id（写手台账里报的）：置这些伏笔为已收尾、记下回收章。它与 refs
    无关，不管这一稿有没有交 refs 都照办。
    """
    remap: dict[tuple[str, str], str] = {}
    if refs is not None:
        remap = await _apply_changes(conn, novel_id, chapter_id, changed_entries or [])
        if remap:
            refs = _repoint(refs, remap)

    created = await _create_entities(conn, novel_id, chapter_id, new_entries or [])
    # 新造的也挂一条 ref（一定是关键戏份），跟报上来的一起去重（按 (refType, refId) 只留一条）。
    merged = normalize_refs([*(refs or []), *created])

    if refs is not None:
        await conn.execute(DELETE_REFS, (chapter_id,))

    # 伏笔收尾与 refs 分开：它是状态翻转，不是关联。放在早退 return 0 之前，免得"这一章只收尾、
    # 没别的关联"时被漏掉。
    await _resolve_foreshadowings(conn, novel_id, chapter_id, resolved or [])

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


async def write_lines(conn, novel_id: str, chapter_id: str, chapter_order: int, lines) -> None:
    """把这一章报的阶段线 / 支线写进 novel_outline，跑在章节写入的同一事务里。

    先撤掉"从这一章起头"的 phase / branch（重写这一章时旧的开线不该留着），再按台账重挂：
      open     → 新插一行，startChapterId = 这一章；id 用行里预生成的（好让同一章新开的支线
                 能挂到同一章新开的阶段线下），parentId 挂父（阶段线→主线、支线→阶段线）；
      close    → 把目标行置 completed = true；收的是阶段线时，把它名下仍开着的支线一并收尾；
      continue → 沿用；带内容就顺带刷新那一行。
    lines 为空（没报）就一行不动 —— 与 refs 的 None 同思路，这一稿没说的事别去改它。
    chapter_id 必须是已落库的章节 id（新开线的 startChapterId 要指向它）。
    """
    if not lines:
        return
    await conn.execute(DELETE_STARTED_LINES, (novel_id, chapter_id))
    for line in lines:
        if line["action"] == "open":
            await conn.execute(
                LINE_INSERT,
                (
                    line.get("id") or uuid.uuid4().hex,
                    novel_id,
                    line["level"],
                    SETTING_STATUS,
                    chapter_order,
                    line["content"],
                    line.get("parentId") or None,
                    chapter_id,
                ),
            )
        elif line["action"] == "close":
            await conn.execute(LINE_CLOSE, (line["id"], novel_id))
            if line["level"] == "phase":
                await conn.execute(LINE_CLOSE_CHILDREN, (novel_id, line["id"]))
        elif line["action"] == "continue" and line["content"]:
            await conn.execute(LINE_UPDATE_CONTENT, (line["content"], line["id"], novel_id))


async def write_outline_refs(conn, novel_id: str, chapter_id: str, outline_refs) -> int:
    """把这一章所处的大纲（阶段线 / 支线）挂进 novel_chapter_ref，读它的不是模型、是代码。

    outline_refs 是 collect 从 card 的 phase / branch 派生的 ref 列表（每条线的 id 就是
    novel_outline 那行的 id）。**None 表示这一稿不动大纲 ref**（改稿路径）—— 一行不删一写，
    留着上一稿的；给了列表就整批换：先删这一章的 outline ref，再逐条核 id 真存在后写入。
    存在性同样走 _live_ids：continue / close 的 id 照抄 card，可能是模型编的一个不存在的 id。
    """
    if outline_refs is None:
        return 0
    await conn.execute(DELETE_OUTLINE_REFS, (chapter_id,))
    if not outline_refs:
        return 0
    live = await _live_ids(conn, novel_id, outline_refs)
    written = 0
    for ref in outline_refs:
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
