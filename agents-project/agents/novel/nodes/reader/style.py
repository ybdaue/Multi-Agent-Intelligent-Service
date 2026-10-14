"""style 节点：文风审查（非流式，无工具）。"""
from langchain_core.runnables import RunnableConfig

from ...utils.prompt import R_STYLE_PROMPT
from .helpers import _plain_review, _style_backup, _style_main
from .state import ReaderState


async def style(state: ReaderState, config: RunnableConfig) -> dict:
    """文风审查：审的是给前端的判路依据，非流式。"""
    return {"style_report": await _plain_review(
        _style_main, _style_backup, R_STYLE_PROMPT, state.get("style_input") or "", "文风"
    )}