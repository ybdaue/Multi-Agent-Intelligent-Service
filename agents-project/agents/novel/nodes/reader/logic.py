"""logic 节点：连贯性审查（非流式，无工具）。"""
from langchain_core.runnables import RunnableConfig

from ...utils.prompt import R_LOGIC_PROMPT
from .helpers import _logic_backup, _logic_main, _plain_review
from .state import ReaderState


async def logic(state: ReaderState, config: RunnableConfig) -> dict:
    """连贯性审查：审的是给前端的判路依据，非流式。"""
    return {"logic_report": await _plain_review(
        _logic_main, _logic_backup, R_LOGIC_PROMPT, state.get("logic_input") or "", "连贯性"
    )}