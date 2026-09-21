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
    # 用户这一轮的原话。collect 把它追加进 messages 之后清空 —— 只追加一次，重跑不会重复。
    user_message: str
    # 六项攒在这里，确认过才整本落库。普通字典（没有 reducer）：collect 并完再写回整份。
    settings: dict
    # collect 这一轮问出去的话。wait 拿它 interrupt，与流给用户的 token 是同一段。
    question: str
    approved: bool
    # 已经落过库了：重复 POST 同一个 id 不许再写一遍（大纲与世界规则表没有 ON CONFLICT）。
    saved: bool
    # 落库之后给用户的一句话，由 setup.py 的 final 事件带走。
    edit_note: str
