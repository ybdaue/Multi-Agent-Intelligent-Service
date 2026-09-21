"""开书 agent 的系统提示：提示词 + setupSkill 里那几篇用得上的资料。

资料是**模块级读一次**的常量，直接拼进 system prompt —— 这个 agent 不挂工具（问题要逐字流给
用户，工具调用的文字流不出来，见 api/novel/setup.py），所以备选值只能这样给到模型。

只带三篇：SKILL.md 里有六问的全部备选值；character-building 管主角与反差点怎么拟，
plot-structures 管套路与核心冲突怎么拟。情绪曲线 / 黄金开篇 / 提示词完善 / 各种模板是大纲
阶段的事，不在收集范围内，带了只会让模型把理论抄给用户。
"""
from ..utils.skills import SkillError, skill_path
from .prompt import SETUP_PROMPT

SKILL = "setupSkill"

# 用得上的那几篇，顺序即拼进提示词的顺序。
_SOURCE_FILES = (
    "SKILL.md",
    "references/character-building.md",
    "references/plot-structures.md",
)


def _read(rel: str) -> str:
    try:
        path = skill_path(SKILL, rel)
    except SkillError:
        return ""
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _build_system() -> str:
    blocks = [SETUP_PROMPT]
    material = [_read(rel) for rel in _SOURCE_FILES]
    material = [text for text in material if text]
    if not material:
        # 技能包不在（或读不了）也别让服务起不来：只少点备选值，模型自己的爆款经验还够用。
        return SETUP_PROMPT
    blocks.append(
        "# 开书资料\n\n"
        "下面是番茄爆款的开书口径，**只取各问的备选值和拟稿口径**，不要把里面的理论、模板、"
        "章节规划说给用户听。\n\n" + "\n\n---\n\n".join(material)
    )
    return "\n\n".join(blocks)


SETUP_SYSTEM = _build_system()
