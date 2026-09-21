"""喂给模型的对话历史，以及攒多了之后的长期精简。

短期：最近 HISTORY_LIMIT 条原样给。长期：超过 COMPACT_THRESHOLD 条时，由 nodes/compact.py
把早的那批压成一段摘要存进 state.chat_summary，原文用 RemoveMessage 从 messages 里删掉 ——
messages 是 state 里唯一会无限长的通道，checkpoint 每存一份快照就复制一整份。

用户那句话走 state.user_message（每轮被覆盖），是 intension 节点把它写回 messages 的，
所以这里用户与助手两边都在，能拼成一段真对话。
"""
from langchain_core.messages import AIMessage, HumanMessage

# prompt 里原样保留的最近条数（约 6 轮）
HISTORY_LIMIT = 12
# 攒到这么多条才压一次。每轮都压等于每轮多花一次模型调用，摘要也会越压越糊。
COMPACT_THRESHOLD = 24


def _cut_at_user(messages, limit: int) -> list:
    """最近 limit 条，且从用户消息开头起（最多让到该窗口里第一条用户的话）。

    切在助手回复中间，模型看到的历史就是半截的"助手：…"串，会以为自己没看到用户说过的话
    （实测它会直接答"对话记录里只留下了我的回复"）。窗口里一句用户的话都没有就一条不给。
    """
    tail = list(messages)[-limit:]
    for index, message in enumerate(tail):
        if isinstance(message, HumanMessage) and message.content:
            return tail[index:]
    return []


def _line(message) -> str:
    """一条消息渲染成一行；不是给用户看的话（工具调用中间态）给空串。"""
    if isinstance(message, HumanMessage) and message.content:
        return f"用户：{message.content}"
    if (
        isinstance(message, AIMessage)
        and not getattr(message, "tool_calls", None)
        and message.content
    ):
        return f"助手：{message.content}"
    return ""


def render_history(messages, summary: str = "") -> str:
    """一段消息（外加长期摘要）渲染成给模型看的文本；什么都没有就给"（无历史）"。"""
    lines = [f"【更早对话摘要】\n{summary.strip()}"] if summary and summary.strip() else []
    lines += [line for line in map(_line, messages) if line]
    return "\n".join(lines) or "（无历史）"


def recent_history(messages, summary: str = "", limit: int = HISTORY_LIMIT) -> str:
    """这一轮喂给模型的历史：长期摘要 + 最近 limit 条原文。"""
    return render_history(_cut_at_user(messages, limit), summary)


def split_for_compact(messages, keep: int = HISTORY_LIMIT) -> tuple[list, list]:
    """收尾精简时的分堆：要压进摘要的那批 + 原样留着的尾巴（尾巴的口径同 recent_history）。"""
    tail = _cut_at_user(messages, keep)
    return list(messages)[: len(messages) - len(tail)], tail
