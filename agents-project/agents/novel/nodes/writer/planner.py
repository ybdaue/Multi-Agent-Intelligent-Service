"""planner 节点：模型看材料（不看上一章全文）出一张任务卡，拼进写手的开场白。"""
from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from ...tools import fetchDB
from ...utils.prompt import PLANNER_PROMPT
from ..utils.config import tool_config
from ..utils.reply import last_reply
from .helpers import (
    _briefing,
    _chosen_inspirations,
    _parse_card,
    _planner_input,
    _planner_main,
)
from .state import WriterState

# planner 会按需查库（本章突然要用很久以前出现的角色/势力等，材料里没给到细节时点查一条）。
# 工具调用硬限 2 次：提示词写明"最多查一次"，这里再用中间件挡住反复 ReAct（超额的调用被挡回，
# 模型照已有信息把卡出完，不会整个中断）。
_planner_agent = create_agent(
    model=_planner_main,
    tools=[fetchDB],
    middleware=[ToolCallLimitMiddleware(run_limit=2, exit_behavior="continue")],
    system_prompt=PLANNER_PROMPT,
    state_schema=WriterState,
)


async def planner(state: WriterState, config: RunnableConfig) -> dict:
    """出任务卡：模型看材料（不看上一章全文）出一张卡，把卡拼进写手的开场白。"""
    handed = {
        "chapter_attempt": state.get("chapter_attempt", 0) + 1,
        "chapter_review": {"passed": True, "problems": ""},
    }
    bundle = state.get("bundle") or {}
    if not bundle:
        return {
            **handed,
            "task_card": {},
            "chapter_inspirations": [],
            "messages": [HumanMessage(content="拿不到当前这本书的编号，写不了。")],
        }

    card = {}
    if _planner_agent is not None:
        try:
            result = await _planner_agent.ainvoke(
                {"messages": [HumanMessage(content=_planner_input(state))]},
                config=tool_config(config),
            )
            card = _parse_card(last_reply(result.get("messages")))
        except Exception:
            card = {}
    # 本章最终要用的灵感：代码从「必用 ∪ 用户点名 ∪ planner 从可选里挑的」合并定，不由模型拍板。
    chosen = _chosen_inspirations(state, card, bundle.get("inspirations") or {})
    return {
        **handed,
        "task_card": card,
        "chapter_inspirations": chosen,
        "messages": [HumanMessage(content=_briefing(state, card, chosen))],
    }