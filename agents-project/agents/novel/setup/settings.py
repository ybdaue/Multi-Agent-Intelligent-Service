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
    "novel_tropes",
    "novel_style",
    "novel_protagonists",
    "novel_outlines",
    "novel_world_rules",
    "novel_title",
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

# 设定项之间的依赖关系：键改动时，值列表里的项也受牵连需要重议。
DEPENDENCIES: dict[str, list[str]] = {
    "novel_tropes": ["novel_outlines", "novel_world_rules"],
    "novel_world_rules": ["novel_outlines"],
    "novel_protagonists": ["novel_outlines"],
}

# collect_sub 子图内 discuss 节点用的精简提示词：只告诉模型当前在定哪一项、目的、
# 可参考的备选值，不再携带整份六项设定。
FIELD_PROMPTS: dict[str, str] = {
    "novel_title": """当前在定【书名】。用户对书名的想法可能很模糊（一个词、一种感觉），
你的任务是通过聊天帮他把书名敲定下来。

给选项：如果用户说不出具体书名，给 3-5 个跟他题材匹配的书名选项让他挑。
如果他说了一个方向（比如「末世相关的」），就顺着那个方向拟几个具体的。

书名不需要很长，2-6 个字最好，要有辨识度、好记。
用户确认了就行，不用反复确认。""",

    "novel_tropes": """当前在定【小说套路（情绪标签 + 题材 + 爽点模式）】。
这是读者搜书时最先看到的东西，决定书的定位。

情绪标签（决定算法推荐）：打脸爽文 / 极致虐恋 / 爆笑反套路 / 悬疑惊悚 / 治愈甜宠 / 脑洞大开 / 热血 / 虐心
题材：末世 / 修仙 / 游戏 / 历史 / 都市异能 / 科幻 / 悬疑推理 / 现代言情 / 古代言情 / 奇幻玄幻 / 武侠仙侠 / 历史架空 / 都市现实
爽点模式：重生打脸 / 扮猪吃虎 / 升级碾压 / 经营建造 / 越级挑战 / 身份揭秘 / 退婚打脸 / 拍卖会装逼

给出完整的三件套组合让用户确认。如果他只说了题材，你补上常见的情绪标签和爽点模式。
如果他说的组合不常见但有意思，也可以保留。

	注意：用标签和概念举例，不要举具体书名的例子。""",

    "novel_style": """当前在定【小说风格（叙事节奏 + 语言风格）】。

叙事节奏：快节奏（每章一个小高潮）/ 慢热铺垫 / 张弛有度 等
语言风格：轻松诙谐 / 严肃正剧 / 文笔细腻 / 口语化 等

给用户几个常见组合选项，或者让他说个感觉你来匹配。风格要和题材搭配——末世配快节奏+口语化，
修仙配慢热+文笔细腻这样。

	注意：用风格标签搭配来说明，不要拿具体书名做例子。""",

    "novel_protagonists": """当前在定【主角】。需要确定：姓名、性别、身份、性格、
金手指或核心能力、反差点。

主角原型参考：英雄型（勇敢正义）/ 成长型（从弱小到强大）/ 反英雄型（道德灰色）/ 平凡型（普通人卷入非凡事）
常见反差点：表面摆烂实际卷王 / 社恐被迫打脸 / 被虐后觉醒反杀 / 老实人黑化 / 隐藏大佬装萌新 / 看似废柴实天赋异禀

可以一次问几项，但每一项都要有明确的答案再定下来。
用户说「随便」时，按题材给一个完整的主角设定让他确认。
主角可以不止一个（双主角/群像），但要确保每个都有名字和核心特征。

最终确认时把完整的主角信息汇总给他看。

	注意：用角色原型标签来举例，不要用具体小说里的角色名或书名当例子。""",

    "novel_outlines": """当前在定【核心冲突】—— 整个故事最根本的矛盾和驱动力。

核心冲突类型参考：生死存亡 / 查明真相 / 爱情阻碍 / 复仇雪恨 / 权力争夺 / 成长突破 / 守护保护

这是六项里最难定的一项，需要反复聊透：
1. 先理解前面定好的套路、主角、世界观，冲突要跟它们匹配
2. 给 2-3 个冲突方向让用户挑（比如「末世重生」配「复仇+生存vs.人性考验」）
3. 如果他都不满意，继续聊：问他「那你觉得主角最大的对手应该是什么？」引导他说出念头
4. 他说的方向你扩成一个完整的冲突描述，让他确认

核心冲突要具体：不只是「打怪升级」，而是「在丧尸围城的末世里，主角带着前世记忆
不仅要活下去，还要找到前世背叛自己的真相」。

	注意：用概念描述冲突方向，不要用具体小说情节或书名做例子。""",

    "novel_world_rules": """当前在定【世界观 / 等级力量体系】。

需要定的是：世界观背景设定、如果有力量体系要定等级框架、主要势力格局。

如果题材是现代的（都市/悬疑），力量体系可以没有或很弱，重点是世界观氛围和规则。
如果题材是玄幻/修仙/游戏，力量体系是重点——等级名称、突破方式、力量来源。

给用户选项时按题材来：
- 修仙：练气→筑基→金丹→元婴→化神 这类
- 末世：异能觉醒→等级进阶 这类
- 游戏：职业体系+技能树 这类

世界规则可以多条，每条一个命名。

	注意：用概念描述世界观类型，不要用具体小说的世界观做例子。""",
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
# 一段内容的终点是下一个【设定项】、本轮标记块的收尾【设定结束】，或整段回复到头。
SETTING_MARK = "【设定项】"
SETTING_END = "【设定结束】"

_BLOCK = re.compile(
    r"【设定项】\s*([^\s【】]+)\s*【内容】\s*(.*?)"
    r"(?=" + re.escape(SETTING_MARK) + r"|" + re.escape(SETTING_END) + r"|\Z)",
    re.S,
)

# 标记块的起止。**api/novel/stream.py 的 SettingFilter 直接复用下面的 SettingScanner**，
# 所以"从哪儿起不再发给前端"只有这一处定义：流出去的 token 拼起来 == interrupt 里问出去的
# 那句话，是构造出来的，不靠两个解析器各认一遍。
_MARK = re.compile(r"(?:^|\n)[ \t>*#-]*" + re.escape(SETTING_MARK) + r"[ \t*]*")
# 收尾标记**不长尾巴**：标记后面再吃装饰符号（`**【设定结束】**` 这种）会吃掉"可能还没到"的
# 字符 —— 同一个回复逐块喂与整段喂的结果就不一样了，前端"流完再整段替换"会看出跳变。
_END = re.compile(r"(?:^|\n)[ \t>*#-]*" + re.escape(SETTING_END))

# 模型偶尔会写中文名而不是字段名，一并认。
_FIELD_BY_LABEL = {label: field for field, label in SETTING_LABELS.items()}
_FIELD_BY_LABEL.update({field: field for field in SETTING_FIELDS})


def wrap_setting(field: str, content: str) -> object:
    """把一项设定包成 novel 里的存法。

    标量字段（书名/套路/风格）直接存字符串。列表字段（主角/冲突/世界观）包成 [{key: content}]，
    对主角额外从文本中提取 name 字段，避免入库时显示"未命名"。
    """
    key = ITEM_KEY.get(field)
    if not key:
        return content
    entry: dict[str, str] = {key: content}
    if field == "novel_protagonists":
        m = re.search(r"姓名[：:]\s*([^；，、\n\r]+)", content)
        entry["name"] = m.group(1).strip() if m else content.split("；")[0].split("，")[0].strip()[:20]
        if m:
            # description 里去掉"姓名：xxx"前缀，只保留详细信息
            tail = content[m.end():].strip().lstrip("；，、").strip()
            if tail:
                entry["description"] = tail
    elif field == "novel_world_rules":
        name = content.split("：")[0].split("→")[0].split("：")[0].strip()[:20]
        entry["name"] = name if name else content[:20]
    return [entry]


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


# 末尾扣留的字符数：标记可能被切成两半，手里扣着一小截才认得出来。比标记本身长出一截，
# 顺带兜住行首那点装饰符号（`** 【设定项】` 这种）—— 扣留期间扣住的那个换行不能先发出去，
# 否则标记到了手里已经不在行首，就认不出来了。
_HOLD = max(len(SETTING_MARK), len(SETTING_END)) + 18


class SettingScanner:
    """把模型的回复切成「给用户看的散文」与「标记块」，一块一块喂也能得到同一结果。

    流式那一头（api/novel/stream.py 的 SettingFilter）与落库那一头（collect 调 split_reply）
    共用这一份状态机，"发出去的 token 拼起来" == interrupt 里问出去的那句话就不再是"两个
    解析器各认一遍、但愿认在同一处"，而是同一个东西的两种喂法。

    规则（与 prompt.py 里写的格式同一口径）：
    - 散文照发；行首碰到【设定项】就闭嘴，直到行首的【设定结束】为止，中间一个字都不发。
    - 【设定结束】之后又是散文 —— 标记块夹在人话中间、或先说块后说话，后面那段都还在。
      （从前是"见到【设定项】就一律闭嘴到底"，模型把话写在块后面时，那段话就永远丢了。）
    - 模型漏写【设定结束】就闭嘴到底：宁可这一轮少说几句，也不把标记块和一段 JSON 摆给用户。
    """

    def __init__(self) -> None:
        self.buf = ""
        self.dropped = 0     # 已从 buf 前部处理掉的字符数，即 buf[0] 在整段回复里的位置
        self.blocks = ""     # 收走的标记块（含两头标记），交给 parse_setting_blocks 解析
        self.inside = False  # 当前在标记块里，不往外发

    def feed(self, chunk: str) -> list[str]:
        self.buf += chunk or ""
        out: list[str] = []
        while True:
            if self.inside:
                match = _END.search(self.buf)
                if match is None:
                    break
                self.blocks += self.buf[: match.end()]
                self._cut(match.end())
                self.inside = False
                continue
            match = self._find_mark()
            if match is None:
                self._emit(out, self.buf[: max(0, len(self.buf) - _HOLD)])
                self._cut(max(0, len(self.buf) - _HOLD))
                break
            # 起点连同它前面那个换行一起算进标记块，散文那头就不留一个空行。
            self._emit(out, self.buf[: match.start()])
            self.blocks += self.buf[match.start(): match.end()]
            self._cut(match.end())
            self.inside = True
        return out

    def finish(self) -> list[str]:
        """整段回复喂完了：扣在手里的那截补发（正憋着的是标记块，丢弃）。"""
        out: list[str] = []
        if self.inside:
            # 漏写了【设定结束】也得让这一项能被解析出来 —— 话不发了，设定照收。
            self.blocks += self.buf
        else:
            self._emit(out, self.buf)
        self.buf = ""
        return out

    def _find_mark(self):
        for match in _MARK.finditer(self.buf):
            # buf 前面处理过一些（dropped > 0）时，"^" 指的是 buf 开头、而不是整段回复的开头，
            # 那种假行首不作数。
            if match.start() == 0 and self.dropped > 0 and not match.group(0).startswith("\n"):
                continue
            return match
        return None

    def _cut(self, n: int) -> None:
        self.dropped += n
        self.buf = self.buf[n:]

    @staticmethod
    def _emit(out: list[str], text: str) -> None:
        if text:
            out.append(text)


def split_reply(reply: str) -> tuple[str, str]:
    """模型这一轮的回复切成 (给用户看的散文, 标记块那段)。

    整段一次性喂给 SettingScanner —— 与流式那头喂 token 是同一个状态机，所以前端"流完再拿
    question 整段替换"看不出跳变。没有标记块就是整段散文、标记块给空串（这一轮只是在问）。
    """
    scanner = SettingScanner()
    prose = "".join(scanner.feed(reply or ""))
    prose += "".join(scanner.finish())
    return prose, scanner.blocks


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
