"""writer 子图装配：prepare → planner → write → collect，收稿后交回父图。"""
from langgraph.graph import END, START, StateGraph

from ...utils.trace import traced
from .collect import collect
from .planner import planner
from .prepare import prepare
from .state import WriterInput, WriterOutput, WriterState
from .write import _writer_agent

# 进出一行人话打印（agents/novel/utils/trace.py），只管调式，不动流程。
# write 那一步是 create_agent 子图，没有能挂打印的节点函数 —— 它的起止看前后两个节点。
_writer_flow = StateGraph(WriterState, input_schema=WriterInput, output_schema=WriterOutput)
_writer_flow.add_node("prepare", traced("writer.prepare")(prepare))
_writer_flow.add_node("planner", traced("writer.planner")(planner))
_writer_flow.add_node("write", _writer_agent)
_writer_flow.add_node("collect", traced("writer.collect")(collect))
_writer_flow.add_edge(START, "prepare")
_writer_flow.add_edge("prepare", "planner")
_writer_flow.add_edge("planner", "write")
_writer_flow.add_edge("write", "collect")
# collect 收稿后直接收工（字数是否合格交给父图的 reader 那一路判），不再回炉。
_writer_flow.add_edge("collect", END)

# 不带 checkpointer：挂进父图时就用父图那个，子图每一步都落在同一个 thread 上。
writer = _writer_flow.compile(name="novel_writer")