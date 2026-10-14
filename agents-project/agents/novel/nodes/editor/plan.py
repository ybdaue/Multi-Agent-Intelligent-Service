"""plan 节点：读懂用户要改什么、改成什么；出不来计划就写一句回话，这一轮什么都不改。"""
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from agents.utils.models import ainvoke_with_fallback, parse_json_value

from ..utils.impact import EDIT_SPEC
from ...utils.prompt import EDIT_PLAN_PROMPT
from .helpers import _conflict_text, _editModel, _editModel_backup, _plan_brief
from .state import EditorState


async def plan(state: EditorState, config: RunnableConfig) -> dict:
    """读懂用户要改什么、改成什么；出不来计划就写一句回话，这一轮什么都不改。"""
    reply = await ainvoke_with_fallback(_editModel, _editModel_backup, [
        SystemMessage(content=EDIT_PLAN_PROMPT), HumanMessage(content=_plan_brief(state))])
    text = reply.content if isinstance(reply.content, str) else ""
    try:
        value = parse_json_value(text)
    except (ValueError, TypeError):
        value = {}
    if not isinstance(value, dict):
        value = {}

    target_type = str(value.get("targetType") or "").strip()
    note = str(value.get("note") or "").strip()
    if not target_type:
        return {
            "plan": {},
            "edit_note": note or "我没听懂要改哪一处。你说清改什么、改成什么，我再动手。",
        }

    if target_type == "chapter":
        # 章号一律取这一轮钉住的那一章（请求里的 chapterId，intension 钉的），模型报什么都不作数。
        order = (state.get("target_chapter") or {}).get("chapter_order")
        if not order:
            # 没钉住 = 他开着的那一章还不在库里（本地新建、还没写出来），没有正文可改。
            return {"plan": {}, "edit_note": "你在的这一章还没写出来，先让它写出来再改。"}
        # 他话里点了别的章号：不动手，请他切过去。改的必须是库里那一行，不能靠模型认。
        if (said := state.get("named_chapter_order")) and said != order:
            return {"plan": {}, "edit_note": _conflict_text(said, order)}
        value["chapterOrder"] = int(order)
        return {"plan": value}

    if target_type not in EDIT_SPEC:
        return {"plan": {}, "edit_note": f"「{target_type}」这类东西改不了。"}

    # 设定这一路只交类型与诉求：改哪几列、是并进已有的一条还是新增，都由 settle 拿着这一类
    # 现有的内容去定 —— 模型从"补充世界观"里挑出来的那一行，正是要被盖掉的那一行。
    return {"plan": {
        "targetType": target_type,
        "summary": str(value.get("summary") or "").strip(),
        "request": str(value.get("request") or "").strip(),
        # 只是线索（照目录抄的名字），不是"就改这一条"的结论：settle 靠它把这一条先捞出来看，
        # 条目多到清单装不下时才不至于漏掉用户点名的那一条。
        "targetName": str(value.get("targetName") or "").strip(),
        "note": note,
    }}