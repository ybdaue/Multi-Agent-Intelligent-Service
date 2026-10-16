"""approve 节点：把"要改什么 + 可能波及哪些"摆给用户，点按钮定夺（同意 / 先不改）。"""
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from agents.utils.models import parse_json_value
from ...utils.model import _intentModel_backup, intentModel
from ...utils.prompt import APPROVE_PROMPT
from ...utils.verdict import verdict
from .state import EditorState

# 前端把这两个做成按钮（形状与 confirm_chapter 一致）：同意就照 impact 摆好的那处改，
# 先不改就整处撤下、一个字都不动。用户仍可打字答（那就交给 APPROVE_PROMPT 判）。
_OPTIONS = [
    {"id": "go", "label": "同意，就这么改"},
    {"id": "cancel", "label": "先不改"},
]

_CANCEL_NOTE = "好，这一处先不动。想改的时候直接说。"
_UNSURE_NOTE = "没看出你同不同意，这次先不动。你要改就说清改成什么样。"


def _choice(answer) -> str:
    """前端按钮回传的那个选项。用户自己打字答的（不是按钮）交空串，由 APPROVE_PROMPT 去判。"""
    try:
        value = parse_json_value(str(answer or ""))
    except ValueError:
        return ""
    if isinstance(value, dict) and value.get("option") in ("go", "cancel"):
        return str(value["option"])
    return ""


def _stop(note: str) -> dict:
    """用户没点头（点了"先不改"、或答复含糊）：撤下 impact 摆好的改动与影响台账 ——
    它们会经 output_schema 交给 update，留着就等于用户说了不改、回头还是改了。

    plan 清空后 _route_after_approve 就把这一轮引到收工，note 由 update 回给用户。
    """
    return {
        "plan": {},
        "setting_changes": [],
        "change_impact": [],
        "edit_feedback": "",
        "edit_note": note,
    }


async def approve(state: EditorState, config: RunnableConfig) -> dict:
    """把"要改什么 + 可能波及哪些"摆给用户，点按钮定夺：同意就动手，先不改就撤下。

    interrupt 之前只读 state：节点恢复时会从头重跑，写在它前面的副作用会走两遍。
    """
    answer = interrupt({
        "text": (
            f"{state.get('approve_text') or ''}\n\n"
            "同意就点下面的按钮，我这就动手；要换成别的改法，直接说一句。"
        ),
        "options": _OPTIONS,
    })

    # 按钮回传的选项认得出就照它定，不必再过模型；用户自己打字答的仍交给 APPROVE_PROMPT 判
    # （它判的就是"同意照这个改 / 要调整方案 / 干脆不改"）。
    choice = _choice(answer)
    if choice == "go":
        return {"plan": state.get("plan") or {}}
    if choice == "cancel":
        return _stop(_CANCEL_NOTE)

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
    return _stop(feedback or _UNSURE_NOTE)