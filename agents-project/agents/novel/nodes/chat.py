"""闲聊 / 提问：挂 fetchDB 查库，答"某章写了什么""某个设定是什么"这类问题。

以前这里只有对话历史 —— 库里的正文与设定一个字都拿不到，问什么都只能靠历史猜。现在挂了
只读的 fetchDB（范围就是当前这本书），答之前先查库；查不到就说查不到，不许编。
这一路只在库里已有东西时才有料可查，库外的（没落库的那一稿）走下面那段上下文另说。
"""
from typing import Annotated, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import add_messages

from ..state import State
from ..tools import fetchDB
from ..utils import _chatModel_backup, CHAT_PROMPT, chatModel, recent_history


class ChatState(TypedDict):
    """只管对话：这一路不写正文也不落库，父图不收它的中间态（工具调用那条不上交）。"""

    messages: Annotated[list[AnyMessage], add_messages]


_chat_agent = create_agent(
    model=chatModel,
    tools=[fetchDB],
    system_prompt=CHAT_PROMPT,
    state_schema=ChatState,
)

_chat_agent_backup = create_agent(
    model=_chatModel_backup,
    tools=[fetchDB],
    system_prompt=CHAT_PROMPT,
    state_schema=ChatState,
)


def _last_reply(messages) -> str:
    """最后一条没有工具调用的助手回复 —— 答完交回父图的就是它。"""
    for message in reversed(messages or ()):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            content = message.content
            if isinstance(content, str) and content.strip():
                return content
    return ""


def _context(state: State) -> str:
    """这一问要摆给模型的东西：对话历史，外加他正看着的那一稿（刚写完还没确认落库）。"""
    parts = [
        "# 当前对话上下文",
        f"对话历史（最新在最后）：\n{recent_history(state.get('messages'), state.get('chat_summary') or '')}",
    ]
    # 这一问可能来自确认环节（见 confirm_chapter 的收尾）：用户没点按钮，而是对着刚写完、
    # 还没确认的那一稿问了一句。他手上只有那一稿的正文，"这里为什么这么写"指的就是它 ——
    # 不摆进来，答的人看不见他正看着的东西。收不收下由他自己定，助手不许替他决定。
    chapter = state.get("active_chapter") or {}
    draft = (chapter.get("chapter_content") or "").strip()
    if draft and not chapter.get("chapter_id"):
        parts.append(
            f"# 用户正看着的这一稿（刚写完，还没确认落库）\n"
            f"第 {chapter.get('chapter_order')} 章"
            f"《{chapter.get('chapter_title') or '未命名'}》：\n\n{draft}\n\n"
            "他是对着这一稿说的话。答他这一句就行 —— 收下还是再改，等他看完自己说。"
        )
    return "\n\n".join(parts)


async def chat(state: State, config: RunnableConfig):
    """答用户这一句。挂 fetchDB，库里已落库的东西能查到，不再只靠对话历史猜。"""
    cfg = (config or {}).get("configurable") or {}
    # config 只挑这两个键递给子图：fetchDB 要拿 novel_id，多带的 thread_id / checkpoint_ns
    # 会给这个没有 checkpointer 的子图种出一份自己的 checkpoint（写章那条子图是挂成节点、
    # 由引擎喂 config，这份是手调，得自己裁）。
    try:
        result = await _chat_agent.ainvoke(
            {"messages": [HumanMessage(content=_context(state))]},
            config={
                "configurable": {
                    "novel_id": str(cfg.get("novel_id") or ""),
                    "user_id": str(cfg.get("user_id") or ""),
                }
            },
        )
    except Exception:
        print("[chat] 主闲聊 agent 失败，尝试备用")
        try:
            result = await _chat_agent_backup.ainvoke(
                {"messages": [HumanMessage(content=_context(state))]},
                config={
                    "configurable": {
                        "novel_id": str(cfg.get("novel_id") or ""),
                        "user_id": str(cfg.get("user_id") or ""),
                    }
                },
            )
        except Exception:
            return {}
    reply = _last_reply(result.get("messages"))
    # 一个字都没答出来就什么都别往 messages 里塞（空回复会被历史口径滤掉，塞了也没意义）。
    return {"messages": [AIMessage(content=reply)]} if reply else {}
