"""prepare 节点：守卫 + 备料；回炉这一趟顺手整理好计划，后面就不走 plan 了。"""
from langchain_core.runnables import RunnableConfig

from ...utils.chapter_information import list_chapters
from ...utils.ledger import fetch_catalog
from .helpers import _is_redo, _redo_plan
from .state import EditorState


async def prepare(state: EditorState, config: RunnableConfig) -> dict:
    """守卫 + 备料；回炉这一趟顺手整理好计划，后面就不走 plan 了。"""
    novel_id = (config.get("configurable") or {}).get("novel_id")
    if not novel_id:
        return {"edit_note": "拿不到当前这本书的编号，改不了。"}

    novel = state.get("novel") or {}
    catalog = (await fetch_catalog(novel_id)).strip()
    chapters = (await list_chapters(novel_id)).strip()

    blocks = [f"《{novel.get('novel_title') or '未命名'}》"]
    blocks.append(
        "库里已有的设定目录（每行是「id 名字」，认类型用；具体内容下一步才摆出来）：\n\n" + catalog
        if catalog
        else "库里还没有任何设定。"
    )
    blocks.append(
        "这本书已有的章节：\n\n" + chapters if chapters else "这本书还没有章节，没有可改的章节。"
    )
    materials = "\n\n".join(blocks)

    chapter = state.get("active_chapter") or {}
    if _is_redo(state) and chapter.get("chapter_order") and not chapter.get("chapter_id"):
        return {"materials": materials, "redo": True, "plan": _redo_plan(state)}
    return {"materials": materials, "redo": False}