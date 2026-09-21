"""法律 agent —— langgraph 编排。

节点实现见 nodes/，提示词/模型/记忆/工具见 utils/，被绑给主模型的子 agent 见 tools/。
"""

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from ..utils.agent_store import create_agent_store
from ..utils.checkpoint import create_checkpoint
from .nodes import *

from .state import State
from .utils.memory import checkin, load_memory, update
from .utils.model import legal_tools
from .utils.retry import with_retry_and_fallback
from .utils.routes import route_after_checkin, use_child_agent

checkpointer = create_checkpoint("legal_agent")
store = create_agent_store("legal_agent")

legal_workflow = StateGraph(state_schema=State)
legal_tool_node = ToolNode(legal_tools)

legal_workflow.add_node("checkin", checkin)
legal_workflow.add_node("preprocessing", preprocessing)
legal_workflow.add_node("Intent", with_retry_and_fallback(_intent_node, _intent_fallback))
legal_workflow.add_node("load_memory", load_memory)
legal_workflow.add_node("assistant", with_retry_and_fallback(_assistant_node, _assistant_fallback))
legal_workflow.add_node("child_agent", legal_tool_node)
legal_workflow.add_node("summary", with_retry_and_fallback(_summary_node, _summary_fallback))
legal_workflow.add_node("update", update)

# checkin 先落库本轮提问/会话行，再决定是否进 preprocessing；即便 preprocessing 解析失败
# 早退到 END，提问也已保存。无文件的轮次直接进 Intent，不走文件节点。
legal_workflow.add_edge(START, "checkin")
legal_workflow.add_conditional_edges(
    "checkin",
    route_after_checkin,
    {"preprocessing": "preprocessing", "Intent": "Intent"},
)
legal_workflow.add_edge("preprocessing", "Intent")
legal_workflow.add_edge("Intent", "load_memory")
legal_workflow.add_edge("load_memory", "assistant")
legal_workflow.add_conditional_edges(
    "assistant",
    use_child_agent,
    {
        "summary": "summary",
        "child_agent": "child_agent",
    },
)
legal_workflow.add_edge("child_agent", "assistant")
legal_workflow.add_edge("summary", "update")
legal_workflow.add_edge("update", END)

legal_agent = legal_workflow.compile(name="legal_agent", checkpointer=checkpointer, store=store)
