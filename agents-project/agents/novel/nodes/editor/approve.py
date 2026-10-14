"""approve 节点：把"要改什么 + 可能波及哪些"摆给用户，等他点头。"""
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from ...utils.model import _intentModel_backup, intentModel
from ...utils.prompt import APPROVE_PROMPT
from ...utils.verdict import verdict
from .state import EditorState


async def approve(state: EditorState, config: RunnableConfig) -> dict:
    """把"要改什么 + 可能波及哪些"摆给用户，等他点头。

    interrupt 之前只读 state：节点恢复时会从头重跑，写在它前面的副作用会走两遍。
    """
    answer = interrupt(
        f"{state.get('approve_text') or ''}\n\n"
        "同意就说一声，我这就动手；要换一处改、或者要改成别的样子，直接说。"
    )
    try:
        reply = await intentModel.ainvoke(
            [SystemMessage(content=APPROVE_PROMPT), HumanMessage(content=str(answer))]
        )
    except Exception:
        try:
            reply = await _intentModel_backup.ainvoke(
                [SystemMessage(content=APPROVE_PROMPT), HumanMessage(content=str(answer))]
            )
        except Exception:
            # 备用也失败时默认通过，不影响用户流程
            return {"plan": state.get("plan") or {}}
    text = reply.content if isinstance(reply.content, str) else ""
    go, feedback = verdict(text, "go")

    if go:
        return {"plan": state.get("plan") or {}}
    # impact 摆下的改动与影响台账得撤掉：它们会经 output_schema 交给 update，
    # 留着就等于用户说了不改、回头还是改了。
    return {
        "plan": {},
        "setting_changes": [],
        "change_impact": [],
        "edit_feedback": "",
        "edit_note": feedback or "没看出你同不同意，这次先不动。你要改就说清改成什么样。",
    }