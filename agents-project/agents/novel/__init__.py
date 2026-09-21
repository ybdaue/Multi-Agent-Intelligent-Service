
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import (
    ToolMessage,
    SystemMessage,
    HumanMessage,
    AnyMessage,
    AIMessage,
    RemoveMessage,
)
from langchain_core.runnables import RunnableConfig
import asyncio
import inspect
import json
import time
import uuid
from ..utils.checkpoint import create_checkpoint
from ..utils.agent_store import create_agent_store
from .state import State


from .utils import classify,route_after_load

novel_workflow = StateGraph(state_schema=State)
checkpointer = create_checkpoint("novel_agent")
store = create_agent_store("novel_agent")


from .nodes import intension,writer,editor,confirm_chapter,reader,chat,load,update,compact

novel_workflow.add_node("intension",intension)
# 闲聊
novel_workflow.add_node("chat",chat)
# 写作
novel_workflow.add_node("writer",writer)
# 优化、修改
novel_workflow.add_node("editor",editor)
# 审完一章：不管过没过都停下来问用户，收下才落库，要改就按 intension 回炉
novel_workflow.add_node("confirm_chapter",confirm_chapter)
# 通用节点
novel_workflow.add_node("load",load)
novel_workflow.add_node("reader",reader)
novel_workflow.add_node("update",update)
# 收尾：对话攒多了压一段长期摘要（一轮的终点，落完库才轮到它）
novel_workflow.add_node("compact",compact)



novel_workflow.add_edge(START,"intension")
novel_workflow.add_conditional_edges(
    "intension",
    classify,
    {
        "write":"load",
        "edit":"load",
        "chat":"chat"
    },
)
# load 之后：书在库里就照意图去写 / 去改；库里没有这本书（fromDB 为假）说明它还没建起来，
# 转 update 回一句引导用户去「新建小说」弹窗 —— 开书是 agents/novel/setup 那个独立图的事。
novel_workflow.add_conditional_edges(
    "load",
    route_after_load,
    {
        "write":"writer",
        "edit":"editor",
        "update":"update",
    },
)
novel_workflow.add_edge("writer","reader")
novel_workflow.add_edge("editor","reader")
# 审完不再自己判去路：一律停下来问用户，去哪儿由 confirm_chapter 的 Command 定。
novel_workflow.add_edge("reader","confirm_chapter")
novel_workflow.add_edge("chat","update")
# 一轮的终点是 compact（对话精简），不是 END —— 它排在落库之后，压不动也不影响本轮结果。
novel_workflow.add_edge("update","compact")
novel_workflow.add_edge("compact",END)

novel_agent = novel_workflow.compile(name="novel_agent", checkpointer=checkpointer, store=store)