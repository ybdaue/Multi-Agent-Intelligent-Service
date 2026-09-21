"""开书六项的常量、落库形状与解析。

哪几项、认不认得出来、怎么落库都定在这里，与 prompt 的标记格式同一口径。顺序**不是提问顺序** ——
问哪一项由模型自己定（见 prompt.py），SETTING_FIELDS 只用来判定"六项齐了没"。

标记块的【内容】有两种：主角与世界规则那两项是一段 JSON（键就是库里的列名，见 _STRUCTURED），
其余四项是散文。JSON 那两项照 ledger 的 NEW_ENTITY_SPEC 归一 —— 开书造出来的主角、世界规则，
与写正文时报进台账"新造"的那些是**同一形状**，前端人物档案 / 世界观两张表、writer 备料、
审稿取档案认的都才是一套字段。
"""
import re

from ...utils.models import parse_json_value
from ..utils.ledger import NEW_ENTITY_SPEC, normalize_new
from ..utils.novel_information import render_protagonists

SETTING_FIELDS: tuple[str, ...] = (
    "novel_title",
    "novel_tropes",
    "novel_style",
    "novel_protagonists",
    "novel_outlines",
    "novel_world_rules",
)

# 说人话时用的名字。brief 里报"还差哪几项"、confirm 列出整份设定，都用这个。
SETTING_LABELS: dict[str, str] = {
    "novel_title": "书名",
    "novel_tropes": "小说套路（情绪标签 + 题材 + 爽点模式）",
    "novel_style": "小说风格（叙事节奏 + 语言风格）",
    "novel_protagonists": "主角（姓名、性别、身份、性格、金手指或核心能力、反差点）",
    "novel_outlines": "核心冲突",
    "novel_world_rules": "世界观 / 等级力量体系",
}

# 列表那三项（主角 / 核心冲突 / 世界规则）退成散文时，整段进哪一列。正常走的是
# _STRUCTURED 那套 JSON 形状（见 to_setting），这里只在 JSON 解不出来时兜底 ——
# 别因为格式上的失误把一项设定判没。
ITEM_KEY: dict[str, str] = {
    "novel_protagonists": "description",
    "novel_outlines": "content",
    "novel_world_rules": "rule",
}

# 【内容】写 JSON 的两项 → ledger 那套实体类型。列名、默认值、必须有的那一列（人物与规则
# 都看 name）全从 NEW_ENTITY_SPEC 来，不再另立一份。
_STRUCTURED: dict[str, str] = {
    "novel_protagonists": "character",
    "novel_world_rules": "world_rule",
}

# 标记格式写死在 prompt.py 里，这里按同一口径解析；一轮可以交多项。
_BLOCK = re.compile(r"【设定项】\s*([^\s【】]+)\s*【内容】\s*(.*?)(?=【设定项】|\Z)", re.S)

# 标记块的起点。**必须与 api/novel/stream.py 的 SettingFilter 同一口径**：那边靠它决定
# "从哪儿起不再发给前端"，这边靠它切出"给用户看的散文"。两边认的位置一样，
# 流出去的 token 拼起来才等于 interrupt 里问出去的那句话。
SETTING_MARK = "【设定项】"
_MARK = re.compile(r"(?:^|\n)[ \t>*#-]*" + re.escape(SETTING_MARK) + r"[ \t*]*")

# 模型偶尔会写中文名而不是字段名，一并认。
_FIELD_BY_LABEL = {label: field for field, label in SETTING_LABELS.items()}
_FIELD_BY_LABEL.update({field: field for field in SETTING_FIELDS})


def wrap_setting(field: str, content: str) -> object:
    """把一项设定包成 novel 里的存法。"""
    key = ITEM_KEY.get(field)
    return [{key: content}] if key else content


def _json_items(content: str) -> list[dict] | None:
    """标记块内容里的 JSON：一个对象当一条，一个数组就是多条；解不出来返回 None。"""
    try:
        payload = parse_json_value(content)
    except (ValueError, TypeError):
        return None
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return None
    return [item for item in payload if isinstance(item, dict)]


def _longest(items: list[dict]) -> str:
    """几条 JSON 对象里，各取最长的那段值（认身份的那一列最长），拼成一段散文。"""
    return "\n".join(
        max((str(v) for v in item.values() if v), key=len, default="") for item in items
    ).strip()


def to_setting(field: str, content: str) -> object:
    """一段标记块内容 → 这一项在 settings 里的存法。

    结构化那两项解 JSON：键照 NEW_ENTITY_SPEC 过一遍（多写的键丢、缺的拿默认值、认不出
    身份的那条整个丢掉，与落库端同一套规则）。解不出来、或一条都没剩下，就退回"整段进
    那一列"——格式上的失误不该把一项设定整个判没。
    """
    ref_type = _STRUCTURED.get(field)
    if ref_type is None:
        return wrap_setting(field, content)

    items = _json_items(content)
    if not items:
        return wrap_setting(field, content)

    entries = normalize_new([{"refType": ref_type, "fields": item} for item in items])
    values = [entry["fields"] for entry in entries]
    if not values:
        # 解出了 JSON 但一条都没剩下（多是没给 name，认不出是什么东西）：把那几条里最长的
        # 那段取回来当散文存 —— 认身份的那一列最长。总比把 JSON 原文摆到用户面前强。
        return wrap_setting(field, _longest(items) or content)
    if ref_type == "character":
        # 这一项问的就是主角，戏份不看模型给什么 —— 它可能写成"配角"，那属于别的项。
        for value in values:
            value["role"] = "主角"
    return values


def _item_key(field: str) -> str:
    """列表那一项里，拿哪一列认"是同一条"（同一轮重复给只留一份）。"""
    ref_type = _STRUCTURED.get(field)
    return NEW_ENTITY_SPEC[ref_type]["key"] if ref_type else "content"


def merge_settings(blocks: list[tuple[str, str]]) -> dict:
    """标记块 → settings 的增量。

    每一项都是**整项替换**：模型这一轮给的那一项就是这一项现在的全部（改口、加一条都以它
    为准，见 prompt 里"把这一项重新给一遍"）。同一轮里同名重复给的只留一份。
    """
    updates: dict = {}
    for field, content in blocks:
        value = to_setting(field, content)
        if not isinstance(value, list):
            updates[field] = value
            continue
        key = _item_key(field)
        updates[field] = list({str(item.get(key) or ""): item for item in value}.values())
    return updates


def missing_fields(settings: dict) -> list[str]:
    """还没定下来的项，按 SETTING_FIELDS 的顺序。"""
    return [field for field in SETTING_FIELDS if not (settings or {}).get(field)]


def split_reply(reply: str) -> tuple[str, str]:
    """模型这一轮的回复切成 (给用户看的散文, 标记块那段)。

    切点在行首的【设定项】上 —— 要求行首是为了不被散文里顺手提到的那三个字带偏。没有标记
    就是整段散文、标记块给空串（这一轮只是在问，还没定下东西）。
    """
    text = reply or ""
    match = _MARK.search(text)
    if not match:
        return text, ""
    return text[: match.start()], text[match.start():]


def _as_field(name: str) -> str | None:
    """标记块里的项名转成字段名，认不出返回 None。

    该写的是字段名（novel_title 这类），但模型常写中文标签，还有写成短的（「主角」）或
    长的（「主角：姓名、性别…」）—— 两边都往对方里比一遍，"说的是同一项"就算认出来。
    """
    name = name.strip()
    if name in _FIELD_BY_LABEL:
        return _FIELD_BY_LABEL[name]
    for label, field in _FIELD_BY_LABEL.items():
        if name in label or label in name or name in field:
            return field
    return None


def parse_setting_blocks(text: str) -> list[tuple[str, str]]:
    """从标记块那段里取出 (字段名, 内容)，按出现顺序。

    认不出的项名、空内容一律丢掉 —— 宁可这一项留到下一轮再定，也不猜一个塞进去。
    """
    blocks = []
    for raw_field, raw_content in _BLOCK.findall(text or ""):
        field = _as_field(raw_field)
        content = (raw_content or "").strip()
        if field and content:
            blocks.append((field, content))
    return blocks


def text_of(value) -> str:
    """一项设定排成人话：标量就是它本身，列表项取出包裹的那段正文。"""
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(next((str(v) for v in item.values() if v), ""))
            elif item:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    return str(value or "")


def render_item(field: str, value) -> str:
    """一项设定排成人话：过目清单与给模型的对账簿都用它（库里的列名不摆出来）。

    主角走 render_protagonists —— 与 writer 备料时读主角是同一份中文读法。世界规则按
    "规则名：内容" 排，与 writer 备料里列世界规则的样子一致。其余项就是散文，取出正文。
    """
    if not value:
        return ""
    if field == "novel_protagonists":
        return render_protagonists({field: value if isinstance(value, list) else [value]})

    items = value if isinstance(value, list) else [value]
    lines = []
    for item in items:
        if field == "novel_world_rules" and isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            rule = str(item.get("rule") or "").strip()
            lines.append(f"{name}：{rule}" if name else rule)
        else:
            lines.append(text_of([item]))
    return "\n".join(line for line in lines if line)


def render_settings(settings: dict) -> str:
    """把整份设定排成人话，confirm 节点列出给用户过目。"""
    lines = []
    for field in SETTING_FIELDS:
        text = render_item(field, (settings or {}).get(field))
        lines.append(f"【{SETTING_LABELS[field]}】\n{text or '（还没定）'}")
    return "\n\n".join(lines)
