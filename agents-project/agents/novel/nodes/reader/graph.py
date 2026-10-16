"""reader 子图装配：gather →（连贯性 ∥ 人物设定 ∥ 文风）三路并行 → save，收结论交回父图。"""
from langgraph.graph import END, START, StateGraph

from ...utils.trace import traced
from .gather import gather
from .logic import logic
from .pacing import pacing
from .save import save
from .state import ReaderInput, ReaderOutput, ReaderState
from .style import style


def _route_after_gather(state: ReaderState):
    """gather 之后的去路：守卫拦下（无新稿）就收工；否则按这一稿的严重程度挑审哪几路 ——
    L2（改了局部事实）只查连贯性与人物设定（logic + pacing），L3 / 没分级走三路全审。"""
    if state.get("chapter_review"):
        return END
    if state.get("change_grade") == "L2":
        return ["logic", "pacing"]
    return ["logic", "pacing", "style"]


# 进出一行人话打印（agents/novel/utils/trace.py），只管调式，不动流程。
_reader_flow = StateGraph(ReaderState, input_schema=ReaderInput, output_schema=ReaderOutput)
_reader_flow.add_node("gather", traced("reader.gather")(gather))
_reader_flow.add_node("logic", traced("reader.logic")(logic))
_reader_flow.add_node("pacing", traced("reader.pacing")(pacing))
_reader_flow.add_node("style", traced("reader.style")(style))
_reader_flow.add_node("save", traced("reader.save")(save))
_reader_flow.add_edge(START, "gather")
# gather 自己定去路（守卫拦下 / 三路并行审）；三路并行由 path 返回节点列表表达。
_reader_flow.add_conditional_edges("gather", _route_after_gather)
_reader_flow.add_edge("logic", "save")
_reader_flow.add_edge("pacing", "save")
_reader_flow.add_edge("style", "save")
_reader_flow.add_edge("save", END)

# 不带 checkpointer：作为节点挂进父图时就用父图那个，子图每一步都落在同一个 thread 上。
reader = _reader_flow.compile(name="novel_reader")