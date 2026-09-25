from langchain_core.runnables import RunnableConfig

from ..state import State
from ..utils.chapter_information import get_writer_context, next_chapter_order


async def resolve(state: State, config: RunnableConfig) -> dict:
    """定下这一轮真正要落哪一章，写成 target 交给前端。顺带查好 writer_context 供 writer/reader 复用。"""
    novel_id = str((config.get("configurable") or {}).get("novel_id") or "")

    if state.get("intension") == "write":
        context = await get_writer_context(novel_id)
        return {
            "target": {
                "kind": "write_next",
                "chapterId": "",
                "order": context["chapter_order"],
            },
            "writer_context": context,
        }

    pinned = state.get("target_chapter") or {}
    order = pinned.get("chapter_order")
    context = await get_writer_context(novel_id, order) if order else {}
    return {
        "target": {
            "kind": "edit",
            "chapterId": pinned.get("chapter_id") or "",
            "order": order,
        },
        "writer_context": context,
    }
