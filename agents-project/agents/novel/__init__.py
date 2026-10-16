
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
import re
import time
import uuid
from ..utils.checkpoint import create_checkpoint
from ..utils.agent_store import create_agent_store
from .utils.model import compressModel, _compressModel_backup
from agents.utils.models import ainvoke_with_fallback
from .utils.prompt import SUMMARIZE_PROMPT
from .state import State

_SUMMARY_RE = re.compile(r"【本章精简】\s*(.*?)(?=【前文总结】|\Z)", re.S)
_PAST_RE = re.compile(r"【前文总结】\s*(.*)", re.S)


async def summarize_chapter(state: State, config: RunnableConfig) -> dict:
    """从已落库的正文压出本章精简与前文总结，写入 DB。不阻塞写→审→确认主线。"""
    chapter = state.get("active_chapter") or {}
    chapter_id = chapter.get("chapter_id") or ""
    if not chapter_id:
        return {}

    novel_id = (config.get("configurable") or {}).get("novel_id")
    if not novel_id:
        return {}

    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT content, "order" FROM novel_chapter WHERE id = %s', (chapter_id,)
        )
        row = await cur.fetchone()
        if not row or not (row[0] or "").strip():
            return {}
        content, order = row

        cur = await conn.execute(
            'SELECT "pastSummary" FROM novel_chapter WHERE "novelId" = %s AND "order" = %s',
            (novel_id, order - 1),
        )
        prev = await cur.fetchone()
        prev_text = ""
        if prev and prev[0]:
            ps = prev[0]
            prev_text = (ps.get("text") or "").strip() if isinstance(ps, dict) else ""

    asked = (
        f"上一版前文总结（到上一章为止的）：\n\n{prev_text}"
        if prev_text
        else "这是本书第一章，没有上一版前文总结。"
    )
    reply = await ainvoke_with_fallback(compressModel, _compressModel_backup, [
            SystemMessage(content=SUMMARIZE_PROMPT),
            HumanMessage(content=f"{asked}\n\n这一章的正文：\n\n{content}"),
        ])
    text = reply.content if isinstance(reply.content, str) else ""
    summary = m.group(1).strip() if (m := _SUMMARY_RE.search(text)) else ""
    past = m.group(1).strip() if (m := _PAST_RE.search(text)) else ""
    if not summary and not past:
        return {}

    async with pg_pool.connection() as conn:
        await conn.execute(
            'UPDATE novel_chapter SET summary = %s, "pastSummary" = %s::jsonb WHERE id = %s',
            (summary, json.dumps({"text": past}, ensure_ascii=False), chapter_id),
        )
    return {}


from .utils import (
    classify,
    route_after_chat,
    route_after_draft,
    route_after_load,
    route_after_resolve,
    traced,
)

novel_workflow = StateGraph(state_schema=State)
checkpointer = create_checkpoint("novel_agent")
store = create_agent_store("novel_agent")


from .nodes import intension,writer,editor,confirm_chapter,reader,chat,load,resolve,update,compact

# traced 只是给调式看的进出打印（agents/novel/utils/trace.py），不影响 state 与控制流。
# writer / editor / reader 是编译好的子图、节点函数就是子图本身，挂不上这一层 ——
# 它们的执行流程看子图内部那几个节点（writer.planner、editor.settle 这类）。
novel_workflow.add_node("intension",traced("intension")(intension))
# 闲聊
novel_workflow.add_node("chat",traced("chat")(chat))
# 写作
novel_workflow.add_node("writer",writer)
# 优化、修改
novel_workflow.add_node("editor",editor)
# 审完一章：不管过没过都停下来问用户，收下才落库，要改就按 intension 回炉
novel_workflow.add_node("confirm_chapter",traced("confirm_chapter")(confirm_chapter))
# 通用节点
novel_workflow.add_node("load",traced("load")(load))
# 定这一轮要落哪一章（确定性，不调模型）：load 之后、动笔之前，前端据它给在流的稿定归属
novel_workflow.add_node("resolve",traced("resolve")(resolve))
novel_workflow.add_node("reader",reader)
novel_workflow.add_node("update",traced("update")(update))
# 摘要从正文压出，写入 DB；不阻塞主线
novel_workflow.add_node("summarize_chapter",traced("summarize_chapter")(summarize_chapter))
# 收尾：对话攒多了压一段长期摘要（一轮的终点，落完库才轮到它）
novel_workflow.add_node("compact",traced("compact")(compact))



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
# load 之后：书在库里就先去 resolve 定目标；库里没有这本书（fromDB 为假）说明它还没建起来，
# 转 update 回一句引导用户去「新建小说」弹窗 —— 开书是 agents/novel/setup 那个独立图的事。
# resolve 排在 load 之后是有意的：书还没建时这条边就把它绕过去了，不会对着空书报出一个
# "第 1 章"的目标、让前端长出一个永远落不了库的幽灵草稿。
novel_workflow.add_conditional_edges(
    "load",
    route_after_load,
    {
        "write":"resolve",
        "edit":"resolve",
        "update":"update",
    },
)
# 目标定了（target 已经随 updates 流发出去）再动笔；正文一个字都还没写。
novel_workflow.add_conditional_edges(
    "resolve",
    route_after_resolve,
    {
        "write":"writer",
        "edit":"editor",
    },
)
# 一稿写完 / 改完：审稿开着去 reader 查一遍，关着直接去 confirm_chapter（见 utils/classify.route_after_draft）。
novel_workflow.add_conditional_edges(
    "writer",
    route_after_draft,
    {
        "reader":"reader",
        "confirm_chapter":"confirm_chapter",
    },
)
novel_workflow.add_conditional_edges(
    "editor",
    route_after_draft,
    {
        "reader":"reader",
        "confirm_chapter":"confirm_chapter",
    },
)
# 审完不再自己判去路：一律停下来问用户，去哪儿由 confirm_chapter 的 Command 定。
novel_workflow.add_edge("reader","confirm_chapter")
# 闲聊不一定就收尾：用户没点确认按钮、而是问了一句时，这一轮是"先答他"，答完还得回去
# 把同一问再摆一次（那一稿仍在 active_chapter 里没落库，见 utils/classify.route_after_chat）。
# 没有待确认的稿就直接去 compact —— 闲聊只答话，不走 update / summarize_chapter 那两笔写库的
# （见 route_after_chat 的说明），收尾只把对话压一压。
novel_workflow.add_conditional_edges(
    "chat",
    route_after_chat,
    {
        "confirm_chapter":"confirm_chapter",
        "compact":"compact",
    },
)
# 一轮的终点是 compact（对话精简），不是 END —— 它排在落库之后，压不动也不影响本轮结果。
# summarize_chapter 在二者之间：从已落的正文压出摘要写回 DB，不阻塞写→审→确认主线。
novel_workflow.add_edge("update","summarize_chapter")
novel_workflow.add_edge("summarize_chapter","compact")
novel_workflow.add_edge("compact",END)

novel_agent = novel_workflow.compile(name="novel_agent", checkpointer=checkpointer, store=store)