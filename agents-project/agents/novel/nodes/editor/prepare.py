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

    # 人工改稿：改后正文随请求带上来了，直接进 manual 节点比对旧台账、定严重程度，不必备
    # catalog / 章节清单那两次料。
    #
    # 这里**不看 _is_redo**：manual_content 非空本身就说明"用户刚点了保存"，是确定的一轮；而
    # "按审查意见改"那条回炉路进来时 manual_content 已被 manual 节点清空（见 editor/manual），
    # 落不到这一条。从前多挂一个 not _is_redo，反倒让上一轮被打断（客户端断开 / 超时，update
    # 没跑）残留下来的审查结论 / 回炉标记，把人工保存顶成了 agent 回炉改写。
    if state.get("manual_content"):
        return {"manual": True}

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