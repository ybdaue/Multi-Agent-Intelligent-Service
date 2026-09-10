from typing import Annotated, AsyncGenerator, Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from agents.finance.saver import BoundedMemorySaver
from mcp import get_tools
from middleware import inject_current_date
from agents.utils.models import MainModel


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    step_count: int


MAX_STEPS = 10


class FinanceAgent:
    def __init__(self):
        self.model = MainModel()
        self.tools = get_tools("finance")
        self.agent = self._build_agent()

    def _build_agent(self):
        model = self.model.bind_tools(self.tools)

        async def call_model(state: AgentState, config):
            step = state.get("step_count", 0) + 1

            # 超过最大步数时友好终止，不再调 LLM
            if step > MAX_STEPS:
                return {
                    "messages": [AIMessage(content="已达最大推理步数，请简化你的查询或拆分为多个问题。")],
                    "step_count": step,
                }

            response = await model.ainvoke(state["messages"], config)
            return {"messages": [response], "step_count": step}

        def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
            last_msg = state["messages"][-1]
            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                return "tools"
            return "__end__"

        builder = StateGraph(AgentState)
        builder.add_node("date_middleware", inject_current_date)
        builder.add_node("assistant", call_model)
        builder.add_node("tools", ToolNode(self.tools))

        builder.add_edge(START, "date_middleware")
        builder.add_edge("date_middleware", "assistant")
        builder.add_conditional_edges(
            "assistant",
            should_continue,
            {"tools": "tools", "__end__": END},
        )
        builder.add_edge("tools", "assistant")

        return builder.compile(
            checkpointer=BoundedMemorySaver(),
        )

    def run(self, query: str, thread_id: str = "default") -> str:
        config = {"configurable": {"thread_id": thread_id}}
        result = self.agent.invoke(
            {"messages": [HumanMessage(content=query)], "step_count": 0},
            config=config,
        )
        return result["messages"][-1].content

    async def stream(self, query: str, thread_id: str = "default") -> AsyncGenerator[str, None]:
        """Stream tokens from the agent with typewriter effect."""
        config = {"configurable": {"thread_id": thread_id}}
        async for msg, metadata in self.agent.astream(
            {"messages": [HumanMessage(content=query)], "step_count": 0},
            config=config,
            stream_mode="messages",
        ):
            node = metadata.get("langgraph_node", "")
            if node == "assistant":
                if isinstance(msg.content, str):
                    if msg.content:
                        yield msg.content
                elif isinstance(msg.content, list):
                    for block in msg.content:
                        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                            yield block["text"]
