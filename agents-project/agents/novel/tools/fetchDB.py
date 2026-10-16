"""查这本书在库里的资料：人物、关系、时间线、物品、伏笔、章节这些。

只读，且只看当前这一本书：书取自 config 里的 novel_id，可查的表在 _SCOPE 里闭合。
表名由 _SCOPE 推出来，列名拼进 SQL 前过一遍标识符校验，值一律走参数绑定。
"""
import json
import re
from typing import Any, Literal

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

# 单元格字符上限：章节正文能有几千字，但也不能一条把上下文吃光。
MAX_CELL = 3_000
# 整条结果的上限，超了截断。压到 1 万字以内：查库结果会滚进后续每一轮 LLM 的输入，
# 结果越肥每轮重发越慢（写手常一次读好几条设定 / 整章）。
MAX_CHARS = 10_000
# 一次最多返回多少行。
MAX_LIMIT = 100

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# 能查的表 → 怎么限定到当前这本书。子表没有 novelId，按父表 id 反查回来。
_SCOPE = {
    **{t: '"novelId" = %s' for t in (
        "novel_chapter",
        "novel_outline",
        "novel_character",
        "novel_world_rule",
        "novel_timeline",
        "novel_faction",
        "novel_chronicle",
        "novel_item",
        "novel_relation",
        "novel_inspiration",
        "novel_foreshadowing",
    )},
    **{t: 'chapterId IN (SELECT id FROM novel_chapter WHERE "novelId" = %s)' for t in (
        "novel_chapter_state",
        "novel_chapter_ref",
    )},
}

# 表名从 _SCOPE 推出来，模型只在这几张里挑，也不会有哪张表在 _SCOPE 里漏掉。
TableName = Literal[tuple(_SCOPE)]

# 能模糊搜的表 → 拿哪几列去匹配。纯关联表（*_ref、*_state）没什么可搜的，传了也当没传。
_SEARCH = {
    "novel_character": ("name",),
    "novel_item": ("name", "description"),
    "novel_faction": ("name",),
    "novel_relation": ("relationType", "description"),
    "novel_timeline": ("title",),
    "novel_chronicle": ("title",),
    "novel_foreshadowing": ("description",),
    "novel_world_rule": ("name", "rule"),
    "novel_outline": ("content",),
    # 带上正文：问"某章里是不是写过 XX""某个人物在哪一章登场"得能搜到 content。
    "novel_chapter": ("title", "summary", "content"),
}

# keyword 里的 % 和 _ 是要搜的字面量，在 _like_value 里自己转义，SQL 这边声明同一个转义符。
_ESCAPE = "\\"
_LIKE_FRAGMENT = '"{column}" ILIKE %s ESCAPE \'{escape}\''


def _like_value(keyword: str) -> str:
    """keyword → ILIKE 模式，反斜杠、% 和 _ 都转义掉，只按普通字符匹配。"""
    for char in (_ESCAPE, "%", "_"):
        keyword = keyword.replace(char, _ESCAPE + char)
    return f"%{keyword}%"


def _cell(value: Any) -> Any:
    """单元格转成能进 JSON 的东西：bytea 只报大小，过长的文本截断。"""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} 字节>"
    if isinstance(value, str) and len(value) > MAX_CELL:
        return f"{value[:MAX_CELL]}…（原 {len(value)} 字符，已截断）"
    return value


@tool
async def fetchDB(
    table: TableName,
    runtime: ToolRuntime,
    filters: dict[str, Any] | None = None,
    keyword: str = "",
    order_by: str = "",
    limit: int = 20,
) -> str:
    """查这本书在库里的资料。只读，范围就是当前这本书，查不到别的书。

    返回 JSON：columns 是列名（据此看这张表里有什么），rows 是各行的值，row_count 是条数。

    要查某个东西就按名字去搜那一条，别整张表捞回来自己筛。例：想知道某件物品的作用，
    就用 fetchDB("novel_item", keyword="<物品名>")；想知道某个角色现在什么身份，
    就用 fetchDB("novel_character", keyword="<角色名>")。

    能查的表（括号里是主要列，其余列看返回的 columns）：
      novel_character 人物（name / sex / age / identity / personality / ability / role /
        firstAppearanceChapterId 首次出现的章）
      novel_relation 人物关系（fromCharId、toCharId 是 novel_character.id / relationType /
        strength / description / firstAppearanceChapterId 首次出现的章）
      novel_timeline 时间线（title / year / description / startChapterId 起始章）
      novel_chronicle 编年史（title / year / content / startChapterId 事件发生的章）
      novel_item 物品（name / type / description / ownerId 持有者 /
        firstAppearanceChapterId 首次出现的章 / status）
      novel_faction 势力（name / type / location / stance / description /
        firstAppearanceChapterId 首次出现的章）
      novel_world_rule 世界规则、力量体系（name / rule /
        firstAppearanceChapterId 首次出现的章 / status）
      novel_outline 大纲（content / level 主线main/阶段线phase/支线branch / startChapterId
        起始章 / completed 是否已收尾）
      novel_foreshadowing 伏笔（description / plantedChapterId 埋设章 /
        resolvedChapterId 回收章 / status）
      novel_chapter 章节（order 序号 / title / summary 精简 / content 正文 / status / wordCount；
        keyword 可搜正文，想知道某章写了什么、某个人物在哪一章出现就用它）
      novel_chapter_state 单章收尾时的状态快照（protagonistState 主角状态 / storyTime 故事内时间 /
        eventProgress 事件进度 / worldState 世界局势）
      novel_inspiration 全书灵感（title 显示名 / category 内容类型数组，可取多个 style/plot/
        character/meme/setting/other / type 素材形态 text/file/url / content；用在哪些章看
        novel_chapter_ref 里 refType='inspiration' 的行）
      novel_chapter_ref 本章关联的人物、势力、时间线、伏笔、物品（refType / refId /
        role 戏份：key 关键 / state 状态 / mention 提及）

    会随剧情演变的设定（character / faction / item / world_rule / relation）每变一次建一版新行，
    旧行的 next 指向它变成的新行（next 为空的那一行才是「当前版」）；每条版本行的
    firstAppearanceChapterId 记它出现在哪一章。

    带 ChapterId 的列（firstAppearanceChapterId / startChapterId /
    plantedChapterId / resolvedChapterId）存的是 novel_chapter.id，不是章节号。
    要按「第几章」判断得先 join novel_chapter 取它的 order。

    Args:
        table: 查哪张表，从上面这几张里挑
        filters: 等值筛选，如 {"role": "主角"}、{"ownerId": "<人物 id>"}；不传是这张表全部
        keyword: 按名字 / 正文模糊搜，用来只捞那一条，如某个物品名、某个角色名。
                 与 filters 一起用时是「且」；纯关联表没有可搜的列，传了也当没传
        order_by: 排序，如 "order"、"createdAt desc"；不传不排
        limit: 最多返回多少行，1~100，默认 20
    """
    novel_id = ((runtime.config or {}).get("configurable") or {}).get("novel_id")
    if not novel_id:
        return "拿不到当前这本书的编号，没法查。"

    order = ""
    if order_by.strip():
        parts = order_by.split()
        if len(parts) > 2 or not _IDENT.fullmatch(parts[0]) or (
            len(parts) == 2 and parts[1].lower() not in ("asc", "desc")
        ):
            return f'order_by 写不对：{order_by}。列名，或列名加 asc / desc，如 "order"、"createdAt desc"。'
        order = f' ORDER BY "{parts[0]}"' + (f" {parts[1].upper()}" if len(parts) == 2 else "")

    where = [_SCOPE[table]]
    params: list[Any] = [novel_id]
    for column, value in (filters or {}).items():
        if not _IDENT.fullmatch(column):
            return f"filters 里的列名不合法：{column}"
        where.append(f'"{column}" = %s')
        params.append(value)

    searched = _SEARCH.get(table, ()) if keyword.strip() else ()
    if searched:
        fragments = [_LIKE_FRAGMENT.format(column=c, escape=_ESCAPE) for c in searched]
        where.append("(" + " OR ".join(fragments) + ")")
        params.extend([_like_value(keyword.strip())] * len(searched))

    params.append(max(1, min(limit, MAX_LIMIT)))

    sql = f"SELECT * FROM {table} WHERE {' AND '.join(where)}{order} LIMIT %s"

    from api.utils.db import pg_pool

    try:
        async with pg_pool.connection() as conn:
            cur = await conn.execute(sql, params)
            columns = [d.name for d in (cur.description or [])]
            rows = await cur.fetchall()
    except Exception as e:
        return f"查询失败：{e}"

    text = json.dumps(
        {
            "columns": columns,
            "rows": [[_cell(v) for v in row] for row in rows],
            "row_count": len(rows),
        },
        ensure_ascii=False,
        default=str,
    )
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "…（结果太长已截断，缩小 filters 或 limit 再查）"
    return text
