"""gather 节点（查库，不调模型）：备三份开场白，台账指向的档案按 refId 从库里取。"""
from langchain_core.runnables import RunnableConfig

from ...utils.chapter_information import get_writer_context
from ...utils.ledger import fetch_ref_facts
from .helpers import _PASSED, _logic_input, _pacing_input, _style_input
from .state import ReaderState


async def gather(state: ReaderState, config: RunnableConfig) -> dict:
    """备材料：复用 resolve 缓存的 writer_context，台账指向的档案按 refId 从库里取。

    守卫：没有本轮新稿（chapter_id 非空、或正文空）就直接判通过、收工。
    """
    chapter = state.get("active_chapter") or {}
    if not chapter.get("chapter_content") or chapter.get("chapter_id"):
        return {"chapter_review": dict(_PASSED)}

    novel_id = (config.get("configurable") or {}).get("novel_id")
    if not novel_id:
        return {"chapter_review": dict(_PASSED)}

    context = state.get("writer_context") or await get_writer_context(
        novel_id, chapter.get("chapter_order")
    )
    facts = await fetch_ref_facts(novel_id, chapter.get("chapter_refs"))
    return {
        "facts": facts,
        "logic_input": _logic_input(state, context),
        "pacing_input": _pacing_input(state, context, facts),
        "style_input": _style_input(state, context),
    }