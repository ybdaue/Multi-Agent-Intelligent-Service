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


ROLE_LABEL = {"user": "用户", "assistant": "助手"}


def visible_messages(messages) -> list[tuple[str, str]]:
    """messages 里"用户 / 助手说过的话"那几条，按 (角色, 内容) 给；工具调用的中间态不算。

    喂给模型的历史与前端重建出来的对话栏共用这一份口径（见 api/novel/agent.py 的 /history）：
    两边不一致的话，用户看到的对话跟他以为 agent 记得的就不是一回事了。
    """
    pairs: list[tuple[str, str]] = []
    for message in messages or ():
        content = getattr(message, "content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        if isinstance(message, HumanMessage):
            pairs.append(("user", content))
        elif isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            pairs.append(("assistant", content))
    return pairs


def last_reply(messages) -> str:
    """末尾那条助手回话；末尾不是助手说的话就给空串。

    用来认出"这一轮的助手回话"：用户在确认环节问了一句、由 chat 答完之后，这一轮停在同一个
    interrupt 上重新摆问题（见 nodes/confirm_chapter）—— 那句话只活在 messages 末尾，前端要
    靠它把"我的问题 → 助手的答复 → 重摆的那一问"摆全（见 api/novel/agent.py 的 question 事件）。

    判据是"末尾"而不是"最后一条助手消息"：写作 / 审稿那几段子图的对话不上交父图，正常停在
    interrupt 上时末尾是 intension 写进去的用户那句话，这儿给空串；换成往上翻着找，就会把
    上一轮的回话当成本轮的推给前端。
    """
    pairs = visible_messages(messages)
    if pairs and pairs[-1][0] == "assistant":
        return pairs[-1][1].strip()
    return ""


def _line(message) -> str:
    """一条消息渲染成一行；不是给用户看的话（工具调用中间态）给空串。"""
    for role, content in visible_messages([message]):
        return f"{ROLE_LABEL[role]}：{content}"
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
