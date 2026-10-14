"""prepare 节点（查库，不调模型）：复用 resolve 缓存的 writer_context，补上一章台账指向设定的档案。"""
from langchain_core.runnables import RunnableConfig

from ...utils.chapter_information import get_writer_context
from ...utils.inspiration import fetch_inspiration_menu
from ...utils.ledger import fetch_chapter_refs, fetch_ref_facts
from .helpers import _constraint_block, _materials
from .state import WriterState


async def prepare(state: WriterState, config: RunnableConfig) -> dict:
    """备料：复用 resolve 缓存的 writer_context，再补上一章台账指向设定的完整档案。

    这一步不调模型，只是把动笔要用的东西一次备齐交给 planner / 写手，省得它们各自再查库。
    灵感菜单也在这取：planner 拿它挑本章要用的灵感，挑完写进 chapter_inspirations。
    """
    novel_id = (config.get("configurable") or {}).get("novel_id")
    if not novel_id:
        return {"bundle": {}}

    context = state.get("writer_context") or await get_writer_context(novel_id)
    order = context.get("chapter_order") or 1
    # 上一章用到的设定，取它们**库里现在的样子**：写手照它保持一致，planner 照它挑 settings。
    refs = await fetch_chapter_refs(novel_id, order)
    prev_facts = await fetch_ref_facts(novel_id, refs)
    menu = await fetch_inspiration_menu(novel_id)
    return {
        # 清掉上一轮残留的本章灵感：这一章要用的由本轮 planner 重定。
        "chapter_inspirations": [],
        "bundle": {
            "order": order,
            "prev_content": context.get("prev_content") or "",
            "prev_facts": prev_facts,
            "materials": _materials(state, context),
            "budget": _constraint_block(context, order),
            "inspirations": menu,
        },
    }