"""editor 子图装配：prepare → plan → settle → impact → approve → revise → collect，边走边判。"""
from langgraph.graph import END, START, StateGraph

from ...utils.trace import traced
from .approve import approve
from .collect import collect
from .helpers import _is_chapter
from .impact import impact
from .manual import manual
from .plan import plan
from .prepare import prepare
from .revise import _revise_agent
from .settle import settle
from .state import EditorInput, EditorOutput, EditorState


def _route_after_prepare(state: EditorState) -> str:
    """人工改稿这一趟直接去 manual（自己比对两稿、报台账、定级）；回炉计划已备好就去 impact；
    正常这一趟先让模型读懂用户要改什么。"""
    if state.get("manual"):
        return "manual"
    return "impact" if state.get("plan") else "plan"


def _route_after_plan(state: EditorState) -> str:
    """出得来计划：设定这一路先去 settle 定夺，章节那一路直接去算范围；出不来就收工。"""
    if not state.get("plan"):
        return "done"
    return "impact" if _is_chapter(state) else "settle"


def _route_after_settle(state: EditorState) -> str:
    """定夺完就去算范围；定不下来（plan 已清空、回话写在 edit_note 里）就收工。"""
    return "impact" if state.get("plan") else "done"


def _route_after_impact(state: EditorState) -> str:
    """impact 之后：没计划就收工；回炉这一趟用户已经同意过了，直接改；正常这一趟先摆给用户看。"""
    if not state.get("plan"):
        return "done"
    return "revise" if state.get("redo") else "approve"


def _route_after_approve(state: EditorState) -> str:
    """点头了：改章节的继续去改，改设定的到此为止（update 会落库）；没点头就收工。"""
    if not state.get("plan"):
        return "done"
    return "revise" if _is_chapter(state) else "done"


# 进出一行人话打印（agents/novel/utils/trace.py），只管调式，不动流程。
# revise 那一步是 create_agent 子图，没有能挂打印的节点函数 —— 它的起止看前后两个节点。
_editor_flow = StateGraph(EditorState, input_schema=EditorInput, output_schema=EditorOutput)
_editor_flow.add_node("prepare", traced("editor.prepare")(prepare))
_editor_flow.add_node("manual", traced("editor.manual")(manual))
_editor_flow.add_node("plan", traced("editor.plan")(plan))
_editor_flow.add_node("settle", traced("editor.settle")(settle))
_editor_flow.add_node("impact", traced("editor.impact")(impact))
_editor_flow.add_node("approve", traced("editor.approve")(approve))
_editor_flow.add_node("revise", _revise_agent)
_editor_flow.add_node("collect", traced("editor.collect")(collect))
_editor_flow.add_edge(START, "prepare")
# 备料之后往哪走、算完范围收工还是继续，都由节点定的条件边判，不由模型挑。
_editor_flow.add_conditional_edges(
    "prepare", _route_after_prepare, {"plan": "plan", "impact": "impact", "manual": "manual"}
)
# manual 自己就把 active_chapter 备好了（用户已改完正文），不走 revise / collect，直接交回父图。
_editor_flow.add_edge("manual", END)
_editor_flow.add_conditional_edges(
    "plan", _route_after_plan, {"settle": "settle", "impact": "impact", "done": END}
)
_editor_flow.add_conditional_edges("settle", _route_after_settle, {"impact": "impact", "done": END})
_editor_flow.add_conditional_edges(
    "impact", _route_after_impact, {"approve": "approve", "revise": "revise", "done": END}
)
_editor_flow.add_conditional_edges(
    "approve", _route_after_approve, {"revise": "revise", "done": END}
)
_editor_flow.add_edge("revise", "collect")
_editor_flow.add_edge("collect", END)

# 不带 checkpointer：挂进父图时就用父图那个，approve 的 interrupt 才能存下来。
editor = _editor_flow.compile(name="novel_editor")