"""改既有内容：能改哪些列、改完哪些地方可能跟着受影响、这两样怎么落库。

editor 只把范围列出来，不判断"这一处到底要不要改"，所以这里全是确定性的结构数据查询，
没有一处语义检索。severity 是启发式初值，不是模型打的分。

改设定：认身份那一列改了 → 正文里写着旧名字的章节（name_ref）；其他列改了 → 台账里报过
这一条的章节（stale_value）。新增一条设定：正文里已经写着这个名字的章节（plot_conflict）——
它还没被哪一章的台账报过，字面匹配是唯一的线索。改章节正文：序号在它之后的章节，其中共用
设定的算 review，其余算 info。落库由 write_edits 做（改的写用户点名的列、新增的插一行、
影响行插 novel_change_impact，靠 (changeId, targetType, targetId, reasonKind) 唯一 +
ON CONFLICT 保证重跑不翻倍）。字段白名单与 ledger.py 认同一份（NEW_ENTITY_SPEC）。
"""
import uuid

from .ledger import FACT_SKIP_COLUMNS, NEW_ENTITY_SPEC, TYPE_LABEL

# 能改的八类：七类照 NEW_ENTITY_SPEC（字段白名单同一份），大纲是外加的（不能新造但能改）。
EDIT_SPEC = {
    ref_type: {
        "table": spec["table"],
        "key": spec["key"],
        "columns": [column for column in spec["columns"] if column not in FACT_SKIP_COLUMNS],
    }
    for ref_type, spec in NEW_ENTITY_SPEC.items()
}
# 大纲认身份那一列就是正文本身：改它等于重写这条大纲，所以它也一定走 name_ref 那条路。
EDIT_SPEC["outline"] = {"table": "novel_outline", "key": "content", "columns": ["content"]}

# 提示词里按这个顺序列给模型，跟 NEW_ENTITY_SPEC 一致，改起来好对。
EDIT_TYPES = tuple(EDIT_SPEC)

# 列名说成人话，写进给用户看的那句"为什么受影响"里（列名本身是 prisma 的）。
_COLUMN_LABELS = {
    "name": "名字",
    "title": "标题",
    "sex": "性别",
    "age": "年龄",
    "birthYear": "出生年份",
    "deathYear": "死亡年份",
    "description": "描述",
    "identity": "身份",
    "personality": "性格",
    "ability": "能力",
    "role": "角色身份",
    "type": "类型",
    "location": "所在地",
    "stance": "立场",
    "rule": "规则内容",
    "year": "年份",
    "content": "内容",
}

# 短到能当名字用、能拿去正文里做字面匹配的那几列。大纲的 content、伏笔的 description 是整段
# 正文，拿它们去 LIKE 只会把每一章都捞出来，所以不匹配。
_NAME_KEYS = ("name", "title")

# 反查台账时算"真有戏份"的 role；只提了一嘴的（mention）不算，由字面匹配那条线去管。
_KEY_ROLES = ("key", "state")

# 一句"为什么受影响"、一个旧值/新值的上限（影响清单是摆给用户看的，不是存档）。
MAX_VALUE_CHARS = 500
MAX_REASON_CHARS = 300

# 一次改动最多列多少行（改第 3 章时后面几十章都算候选，全列出来用户也读不完）。
MAX_LATER_ROWS = 300
MAX_MATCH_ROWS = 300

# 给 settle 看的同类清单：条数、单格、整份各封一道顶。单格放得比影响清单宽得多 ——
# settle 要照着原文改出"合起来的完整内容"，看不全就会把没看到的那截重写丢。
# 条数与目录（ledger.CATALOG_LIMIT）对齐：plan 认得出名字的，settle 就得看得见那一条。
MAX_ENTRIES = 100
MAX_ENTRY_CELL_CHARS = 1200
MAX_ENTRIES_CHARS = 20_000

# 名字短到一个字时不做字面匹配（"林"这种一搜一大片，全是噪声）。
MIN_MATCH_CHARS = 2


def column_label(column: str) -> str:
    """列名说成人话；表里没有的就原样给出去，总比只显示个英文强。"""
    return _COLUMN_LABELS.get(column, column)


def _clip(value, limit: int = MAX_VALUE_CHARS) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text if len(text) <= limit else f"{text[:limit]}…"


def editable_fields(ref_type: str, fields) -> dict:
    """模型要改的那几列过一遍白名单：认不出的类型、不在白名单里的列、非字典一律丢掉。

    空串留着 —— 那是"把这一列清空"的合法要求。
    """
    spec = EDIT_SPEC.get(ref_type)
    if spec is None or not isinstance(fields, dict):
        return {}
    return {
        column: (" ".join(str(fields.get(column) or "").split()))
        for column in spec["columns"]
        if column in fields
    }


async def find_target(novel_id: str, ref_type: str, target_id: str, name: str) -> dict | None:
    """把要改的那一行从库里定位出来，返回它**现在的样子**（只有白名单里的列）。

    id 优先，对不上就拿名字再查一遍（只有认身份那一列短的那几类查得，大纲与伏笔按名字查
    等于乱撞）。查不到就给 None，由调用方回一句"没找到"，不猜。
    """
    from api.utils.db import pg_pool

    spec = EDIT_SPEC.get(ref_type)
    if spec is None:
        return None

    columns = list(spec["columns"])
    select = ", ".join(f'"{column}"' for column in columns)

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            f'SELECT id, {select} FROM {spec["table"]} WHERE "novelId" = %s AND id = %s',
            (novel_id, target_id),
        )
        row = await cur.fetchone()
        if row is None and name and spec["key"] in _NAME_KEYS:
            cur = await conn.execute(
                f'SELECT id, {select} FROM {spec["table"]} '
                f'WHERE "novelId" = %s AND "{spec["key"]}" = %s LIMIT 1',
                (novel_id, name),
            )
            row = await cur.fetchone()

    if row is None:
        return None
    return {"id": row[0], "fields": dict(zip(columns, row[1:]))}


async def list_entries(novel_id: str, ref_type: str, hint: str = "") -> list[dict]:
    """把这一类设定**现有的条目连内容**取回来（只有白名单里的列，status 不在内）。

    settle 拿它跟用户要补的东西比一遍 —— 它得看得见内容才判得出冲不冲突、该并进哪一条。
    条数与篇幅都封顶（见上面那三个常量），所以 hint（用户点名的那个名字）要**排在最前面**：
    条目多了要被截断时，先丢掉的是用户没提的那些，他点名的那一条无论如何都在。
    """
    spec = EDIT_SPEC.get(ref_type)
    if spec is None:
        return []

    columns = list(spec["columns"])
    select = ", ".join(f'"{column}"' for column in columns)

    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            f'SELECT id, {select} FROM {spec["table"]} '
            f'WHERE "novelId" = %s ORDER BY ("{spec["key"]}" = %s) DESC, "createdAt" LIMIT %s',
            (novel_id, hint, MAX_ENTRIES),
        )
        rows = await cur.fetchall()
    return [{"id": row[0], "fields": dict(zip(columns, row[1:]))} for row in rows]


def render_entries(ref_type: str, entries: list[dict]) -> str:
    """同类现有条目排成给 settle 看的清单：一条一版，id 打头，空格子不写。"""
    spec = EDIT_SPEC[ref_type]
    key = spec["key"]
    blocks = []
    for entry in entries:
        fields = entry["fields"]
        head = _clip(fields.get(key), 60) or "（没名字）"
        lines = [f"- id {entry['id']}：{head}"]
        for column, value in fields.items():
            if column == key:
                continue
            text = _clip(value, MAX_ENTRY_CELL_CHARS)
            if text:
                lines.append(f"  {column_label(column)}：{text}")
        blocks.append("\n".join(lines))

    text = "\n".join(blocks)
    if len(text) > MAX_ENTRIES_CHARS:
        text = text[:MAX_ENTRIES_CHARS] + "\n…（清单太长，只列到这里）"
    return text


def field_notes(fields: dict) -> str:
    """新增一条时摆给用户看的"新增内容"：一列一行，空的列不写。

    status 不摆：它是审校状态，新增时由程序补成默认值，用户没有说过它，摆出来只会让人
    以为"这一条的状态是用户定的"。
    """
    lines = []
    for column, value in fields.items():
        if column in FACT_SKIP_COLUMNS:
            continue
        text = _clip(value)
        if text:
            lines.append(f"- {column_label(column)}：{text}")
    return "\n".join(lines)


async def exists_by_key(novel_id: str, ref_type: str, identity: str) -> bool:
    """这一类里是不是已经有一条叫这个名字的了。

    新增前的守卫：清单已经摆给 settle 看过，它还报新增却撞上同名，说明它自相矛盾 ——
    这时候插一条重复的、或者盖到原来那条上，都不可接受，交调用方回一句让用户定。
    """
    spec = NEW_ENTITY_SPEC.get(ref_type)
    if spec is None or not identity:
        return False

    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            f'SELECT id FROM {spec["table"]} WHERE "novelId" = %s AND "{spec["key"]}" = %s LIMIT 1',
            (novel_id, identity),
        )
        return await cur.fetchone() is not None


def _diff(old_fields: dict, new_fields: dict) -> dict[str, tuple]:
    """逐字段比一遍，返回 {列: (旧值, 新值)}。只留真变了的。"""
    changed = {}
    for column, new_value in new_fields.items():
        old_value = str(old_fields.get(column) or "")
        if new_value != old_value:
            changed[column] = (old_value, new_value)
    return changed


def _like(name: str) -> str:
    """把名字做成 LIKE 的模式串，里面的 % _ \\ 先转义（名字里带这些字符的不多，但不能漏）。"""
    escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# 正文里写着旧名字的章节：台账只记 writer 自己报的，改名的字面影响用它兜。
CHAPTERS_MATCHING_SQL = (
    'SELECT id, "order" FROM novel_chapter '
    'WHERE "novelId" = %s AND content LIKE %s ESCAPE \'\\\' '
    'ORDER BY "order" LIMIT %s'
)

# 台账里报过这一条设定的章节，带角色看戏份重不重。
CHAPTERS_WITH_REF_SQL = (
    'SELECT r."chapterId", c."order", r.role FROM novel_chapter_ref r '
    'JOIN novel_chapter c ON c.id = r."chapterId" '
    'WHERE c."novelId" = %s AND r."refType" = %s::"RefType" AND r."refId" = %s '
    'ORDER BY c."order"'
)

# 序号在目标之后的章节（改章节时的候选）。
LATER_CHAPTERS_SQL = (
    'SELECT id, "order" FROM novel_chapter '
    'WHERE "novelId" = %s AND "order" > %s ORDER BY "order" LIMIT %s'
)

# 后面这些章节里报过指定几条设定的那些 —— 跟被改的那一章共用设定，最需要回头看一眼。
LATER_WITH_REFS_SQL = (
    'SELECT DISTINCT c.id FROM novel_chapter_ref r '
    'JOIN novel_chapter c ON c.id = r."chapterId" '
    'WHERE c."novelId" = %s AND c."order" > %s AND r."refType" = %s::"RefType" '
    'AND r."refId" = ANY(%s) AND r.role = ANY(%s)'
)

# 被改的那一章自己报了哪些设定（只取有戏份的），拿来找"跟它共用设定"的后续章节。
CHAPTER_REFS_SQL = (
    'SELECT "refType", "refId" FROM novel_chapter_ref '
    'WHERE "chapterId" = %s AND role = ANY(%s)'
)


def _row(change: dict, *, target_type: str, target_id: str, target_chapter, reason_kind: str,
         reason: str, severity: str, detected_by: str) -> dict:
    """拼一行影响台账，键与 novel_change_impact 的列对齐。"""
    return {
        **change,
        "targetType": target_type,
        "targetId": target_id,
        "targetChapter": target_chapter,
        "reasonKind": reason_kind,
        "reason": reason[:MAX_REASON_CHARS],
        "severity": severity,
        "detectedBy": detected_by,
    }


def _setting_reasons(ref_type: str, changed: dict[str, tuple]) -> list[dict]:
    """一次设定改动按"为什么受影响"分成两路，同一个 reasonKind 只会出现一条。

    1. name_ref：名字 / 标题改了，正文里写着旧名字，字面替换即可（只有短得能当名字用的那两列算）。
    2. stale_value：其余改动（含大纲 / 伏笔那种整段重写），用过它的章节要回头对一遍。

    两路各查各的，同一个章节两边都中就是两行 —— 它们本来就是两件事。
    """
    spec = EDIT_SPEC[ref_type]
    key = spec["key"]
    reasons = []
    name_pair = {}

    if key in changed and key in _NAME_KEYS and changed[key][0]:
        old_value, new_value = changed[key]
        name_pair = {key: changed[key]}
        reasons.append({
            "reasonKind": "name_ref",
            "severity": "must_fix",
            "oldValue": _clip(old_value),
            "newValue": _clip(new_value),
            "why": "正文里写着旧名字，替换掉就行",
            "names": [old_value],
        })

    others = {column: pair for column, pair in changed.items() if column not in name_pair}
    if others:
        pairs = "、".join(
            f"{_COLUMN_LABELS.get(column, column)}：{_clip(pair[0]) or '（空）'} → "
            f"{_clip(pair[1]) or '（空）'}"
            for column, pair in others.items()
        )
        first_old, first_new = next(iter(others.values()))
        reasons.append({
            "reasonKind": "stale_value",
            "severity": "review",
            "oldValue": _clip(first_old),
            "newValue": _clip(first_new),
            "why": f"它改成了（{pairs}），这一章用过它，正文里的说法可能要跟着改",
            "names": [],
        })
    return reasons


async def collect_impact(novel_id: str, *, change_id: str, change_summary: str, ref_type: str,
                         target_id: str, old_fields: dict, new_fields: dict) -> list[dict]:
    """一次设定改动可能波及哪些章节。

    只有真改了的列才算：模型把用户没提的列照抄一遍很常见，那样 diff 是空的，一条都不报。
    """
    changed = _diff(old_fields, new_fields)
    if not changed:
        return []

    spec = EDIT_SPEC[ref_type]
    headline = _clip(old_fields.get(spec["key"]) or new_fields.get(spec["key"]) or "", 60)
    change = {
        "changeId": change_id,
        "changeSummary": change_summary,
        "sourceType": ref_type,
        "sourceId": target_id,
        "oldValue": "",
        "newValue": "",
    }

    from api.utils.db import pg_pool

    rows: list[dict] = []
    async with pg_pool.connection() as conn:
        for reason in _setting_reasons(ref_type, changed):
            base = {
                **change,
                "oldValue": reason["oldValue"],
                "newValue": reason["newValue"],
            }
            seen: set[str] = set()

            if reason["names"]:
                # 名字够长才做字面匹配，一个字的名字搜出来全是噪声。
                name = reason["names"][0]
                if len(name) >= MIN_MATCH_CHARS:
                    cur = await conn.execute(
                        CHAPTERS_MATCHING_SQL, (novel_id, _like(name), MAX_MATCH_ROWS)
                    )
                    for chapter_id, order in await cur.fetchall():
                        if chapter_id in seen:
                            continue
                        seen.add(chapter_id)
                        rows.append(_row(
                            base,
                            target_type="chapter", target_id=chapter_id, target_chapter=order,
                            reason_kind=reason["reasonKind"], severity=reason["severity"],
                            reason=f"第 {order} 章正文里写着「{name}」，{reason['why']}",
                            detected_by="name_match",
                        ))

            if reason["reasonKind"] == "stale_value":
                cur = await conn.execute(
                    CHAPTERS_WITH_REF_SQL, (novel_id, ref_type, target_id)
                )
                for chapter_id, order, role in await cur.fetchall():
                    if chapter_id in seen:
                        continue
                    seen.add(chapter_id)
                    # 只被提一嘴的降到仅供参考：真要去读的是有戏份的那几章。
                    severity = "review" if (role or "") in _KEY_ROLES else "info"
                    rows.append(_row(
                        base,
                        target_type="chapter", target_id=chapter_id, target_chapter=order,
                        reason_kind=reason["reasonKind"], severity=severity,
                        reason=f"第 {order} 章用过【{TYPE_LABEL[ref_type]}】{headline}（{role}），"
                               f"{reason['why']}",
                        detected_by="ref",
                    ))
    return rows


async def collect_new_impact(novel_id: str, *, change_id: str, change_summary: str,
                             ref_type: str, fields: dict) -> list[dict]:
    """新增一条设定：正文里已经写着这个名字的章节，要回头对一遍。

    新条目还没被任何一章的台账报过（CHAPTERS_WITH_REF_SQL 查不出东西），但正文里可能早就
    写了这三个字 —— 第 5 章写了「两界」，你现在加一条「三界」。只有短得能当名字用的那几列
    才做字面匹配，理由同 collect_impact。查不出来就是真空着，交给调用方照实回话。
    """
    spec = NEW_ENTITY_SPEC.get(ref_type)
    if spec is None or spec["key"] not in _NAME_KEYS:
        return []

    name = str(fields.get(spec["key"]) or "").strip()
    if len(name) < MIN_MATCH_CHARS:
        return []

    change = {
        "changeId": change_id,
        "changeSummary": change_summary,
        "sourceType": ref_type,
        # 这一行还没落库，没有 id 可指；认得这次改动的是 changeId。
        "sourceId": "",
        "oldValue": "",
        "newValue": _clip(name),
    }

    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(CHAPTERS_MATCHING_SQL, (novel_id, _like(name), MAX_MATCH_ROWS))
        rows = await cur.fetchall()

    return [
        _row(
            change,
            target_type="chapter", target_id=chapter_id, target_chapter=order,
            reason_kind="plot_conflict", severity="review", detected_by="name_match",
            reason=f"第 {order} 章正文里已经写着「{name}」，新加的这条设定要跟它对一遍",
        )
        for chapter_id, order in rows
    ]


async def collect_chapter_impact(novel_id: str, *, change_id: str, change_summary: str,
                                 chapter_id: str, order: int) -> list[dict]:
    """改了一章，后面哪些章节可能受影响。

    后每一章都算候选，但分两档：跟被改的这一章**共用设定**的给 review（最可能要跟着调），
    其余给 info —— 不然改第 3 章就是把后面每一章都报一遍，用户等于没拿到信息。
    """
    change = {
        "changeId": change_id,
        "changeSummary": change_summary,
        "sourceType": "chapter",
        "sourceId": chapter_id,
        # 章节改动没有"前一版的值"可放（那一整篇正文），两头留空。
        "oldValue": "",
        "newValue": "",
    }

    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(CHAPTER_REFS_SQL, (chapter_id, list(_KEY_ROLES)))
        refs = await cur.fetchall()

        shared: set[str] = set()
        by_type: dict[str, list[str]] = {}
        for ref_type, ref_id in refs:
            by_type.setdefault(ref_type, []).append(ref_id)
        for ref_type, ref_ids in by_type.items():
            cur = await conn.execute(
                LATER_WITH_REFS_SQL,
                (novel_id, order, ref_type, ref_ids, list(_KEY_ROLES)),
            )
            shared.update(row[0] for row in await cur.fetchall())

        cur = await conn.execute(LATER_CHAPTERS_SQL, (novel_id, order, MAX_LATER_ROWS))
        later = await cur.fetchall()

    rows = []
    for later_id, later_order in later:
        if later_id in shared:
            reason = (f"第 {order} 章改过了，这一章在它之后、还跟它用了同一批设定，"
                      f"承接和前后对不上的地方要看一眼")
            severity = "review"
        else:
            reason = f"第 {order} 章改过了，这一章在它之后，只是提个醒"
            severity = "info"
        rows.append(_row(
            change,
            target_type="chapter", target_id=later_id, target_chapter=later_order,
            reason_kind="plot_conflict", severity=severity, reason=reason, detected_by="ref",
        ))
    return rows


def render_rows(rows: list[dict]) -> list[str]:
    """影响行排成给人看的几段，按严重程度分三档、每档限量 —— 摆几百条等于让用户自己去翻。"""
    groups = (
        ("must_fix", "必须改（不改就是错的）", 20),
        ("review", "要你判断（读了才知道该不该动）", 20),
        ("info", "仅供参考", 5),
    )
    blocks = []
    for severity, label, limit in groups:
        picked = [row for row in rows if row["severity"] == severity]
        if not picked:
            continue
        block = [f"{label}，{len(picked)} 处："]
        for row in picked[:limit]:
            block.append(f"- {row['reason']}")
        if len(picked) > limit:
            block.append(f"- …还有 {len(picked) - limit} 处，落库后可以在改动清单里看全")
        blocks.append("\n".join(block))
    return blocks


def render_change(summary: str, notes: list[str], rows: list[dict]) -> str:
    """把这次改动和它的影响范围排成给用户看的一段，approve 节点摆出去等他同意。"""
    lines = [f"我理解你要改的是：{summary}"]

    for note in notes:
        lines.append(note)

    if not rows:
        lines.append("没有查到可能被波及的地方 —— 这条改动没被哪一章的台账报过，正文里也没出现旧名字。")
        return "\n\n".join(lines)

    lines.extend(render_rows(rows))
    lines.append(f"合计 {len(rows)} 处，只标了可能受影响的范围，具体要不要动由你定。")
    return "\n\n".join(lines)


# 影响行靠 (changeId, targetType, targetId, reasonKind) 唯一，重复跑不会翻倍。
IMPACT_INSERT = (
    'INSERT INTO novel_change_impact (id, "novelId", "changeId", "changeSummary", "sourceType", '
    '"sourceId", "oldValue", "newValue", "targetType", "targetId", "targetChapter", "reasonKind", '
    '"reason", severity, status, "detectedBy", "createdAt", "updatedAt") '
    'VALUES (%s, %s, %s, %s, %s::"ImpactTarget", %s, %s, %s, %s::"ImpactTarget", %s, %s, '
    '%s::"ImpactReason", %s, %s::"ImpactSeverity", \'pending\'::"ImpactStatus", %s, now(), now()) '
    'ON CONFLICT ("changeId", "targetType", "targetId", "reasonKind") DO UPDATE SET '
    '"changeSummary" = EXCLUDED."changeSummary", "oldValue" = EXCLUDED."oldValue", '
    '"newValue" = EXCLUDED."newValue", "targetChapter" = EXCLUDED."targetChapter", '
    '"reason" = EXCLUDED."reason", severity = EXCLUDED.severity, '
    '"detectedBy" = EXCLUDED."detectedBy", "updatedAt" = now()'
)


def _update_sql(table: str, columns: list[str]) -> str:
    sets = ", ".join(f'"{column}" = %s' for column in columns)
    return f'UPDATE {table} SET {sets}, "updatedAt" = now() WHERE "novelId" = %s AND id = %s'


async def _insert_setting(conn, novel_id: str, ref_type: str, fields: dict) -> bool:
    """新增一条设定，返回有没有真插进去。只收 NEW_ENTITY_SPEC 里的七类（大纲不在此列）。

    撞名就不插 —— 同名的那条要的其实是"改它"，盖上去就又成了覆盖，而这一轮用户要的是新增。
    缺的列拿默认值补（status 就是这么补上的，schema 里它是 NOT NULL）。章节列
    （startChapterId / firstAppearanceChapterId / plantedChapterId）一律留空：这条是用户
    聊设定时加的，不挂在哪一章上，将来哪一章用到它，writer 的台账会自己补。
    """
    spec = NEW_ENTITY_SPEC.get(ref_type)
    if spec is None:
        return False

    key = spec["key"]
    identity = str(fields.get(key) or "").strip()
    if not identity:
        return False

    cur = await conn.execute(
        f'SELECT id FROM {spec["table"]} WHERE "novelId" = %s AND "{key}" = %s LIMIT 1',
        (novel_id, identity),
    )
    if await cur.fetchone() is not None:
        return False

    columns = list(spec["columns"])
    values = [fields.get(column) or default for column, default in spec["columns"].items()]
    quoted = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    await conn.execute(
        f'INSERT INTO {spec["table"]} ("id", "novelId", {quoted}, "createdAt", "updatedAt") '
        f"VALUES (%s, %s, {placeholders}, now(), now())",
        (uuid.uuid4().hex, novel_id, *values),
    )
    return True


async def write_edits(novel_id: str, setting_changes: list[dict], impact_rows: list[dict]) -> int:
    """把 editor 定下的设定改动和影响台账写进库，返回写了多少行影响。

    跑在自己的事务里，但跟章节那次写入不是一个事务：改章节那一轮的影响台账是附带的，
    它没落上不该把已经写好的章节一起带回去。fields 已在 editor 那边过了白名单
    （改的过 EDIT_SPEC，新增的过 NEW_ENTITY_SPEC，见 editor.settle）。
    """
    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        async with conn.transaction():
            for change in setting_changes or []:
                ref_type = str(change.get("refType") or "")
                fields = change.get("fields") or {}
                if not fields:
                    continue
                if change.get("mode") == "create":
                    await _insert_setting(conn, novel_id, ref_type, fields)
                    continue
                spec = EDIT_SPEC.get(ref_type)
                if spec is None:
                    continue
                columns = [column for column in spec["columns"] if column in fields]
                if not columns:
                    continue
                await conn.execute(
                    _update_sql(spec["table"], columns),
                    (*[fields[column] for column in columns], novel_id, change["refId"]),
                )

            written = 0
            for row in impact_rows or []:
                await conn.execute(
                    IMPACT_INSERT,
                    (
                        uuid.uuid4().hex,
                        novel_id,
                        row["changeId"],
                        row["changeSummary"],
                        row["sourceType"],
                        row["sourceId"],
                        row["oldValue"],
                        row["newValue"],
                        row["targetType"],
                        row["targetId"],
                        row["targetChapter"],
                        row["reasonKind"],
                        row["reason"],
                        row["severity"],
                        row["detectedBy"],
                    ),
                )
                written += 1
    return written
