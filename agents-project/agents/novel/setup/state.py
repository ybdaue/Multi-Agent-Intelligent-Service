"""开书 agent 的 state。

只有这一个 agent 用，所以跟主图的 State 各写各的：这里没有章节、没有意图、没有回炉记账，
只有"六项定到哪一步了"和"这一轮问出去的话"。
"""
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class SetupInput(TypedDict):
    """父层投进来的：用户这一轮的原话（/run 是开场白，/resume 是答复）。"""

    user_id: str
    user_message: str


class SetupState(TypedDict, total=False):
    # better-auth 的用户 id 是 cuid 字符串。落库时用的是 config 里那份，这份只为对上前端投进来的输入。
    user_id: str
    messages: Annotated[list[AnyMessage], add_messages]
    # 用户这一轮的原话。discuss 把它追加进 messages 之后清空 —— 只追加一次，重跑不会重复。
    user_message: str
    # 六项攒在这里，确认过才整本落库。普通字典（没有 reducer）：collect 并完再写回整份。
    settings: dict
    # discuss 这一轮问出去的话，interrupt 用这个值。
    question: str
    approved: bool
    # 已经落过库了：重复 POST 同一个 id 不许再写一遍（大纲与世界规则表没有 ON CONFLICT）。
    saved: bool
    # 落库之后给用户的一句话，由 setup.py 的 final 事件带走。
    edit_note: str

    # maintain 输出的下一轮提问指引
    next_question: str  # 字段名，如 "novel_title"
    next_hint: str      # 详细建议文本
    # maintain 解析的用户本轮选择摘要（用于 discuss 生成问题时参考）
    user_choice: str
    # discuss 这一轮实际问的是哪一项（字段名，空串表示六项已齐、用户在提修改意见）。
    # maintain 用它给提取模型定上下文锚点，也在"上轮编号歧义"时把话题拉回这一项重问。
    asked_field: str