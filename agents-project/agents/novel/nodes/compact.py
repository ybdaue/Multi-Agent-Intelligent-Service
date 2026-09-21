"""收尾精简：对话攒多了，把早的那批压成一段摘要，原文从 messages 里删掉。

摘要必须连着上一版一起重写 —— 只压新的一批，更早的事就一轮轮丢干净了。删原文与换摘要是
同一个 superstep 的一次写入，不会出现"删了却没留下摘要"的中间态。

阈值没到就什么都不做：每轮压一次等于每轮多花一次模型调用，摘要也会越压越糊。这一节点挂在
轮末（update 之后），压不动也不影响这一轮已经落完的库。
"""
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage

from ..state import State
from ..utils import (
    COMPACT_PROMPT,
    COMPACT_THRESHOLD,
    compressModel,
    render_history,
    split_for_compact,
)
from ..utils.retry import with_retry_and_fallback


async def _compact_node(state: State) -> dict:
    messages = state.get("messages") or []
    if len(messages) <= COMPACT_THRESHOLD:
        return {}

    dropped, _ = split_for_compact(messages)
    if not dropped:
        return {}

    summary = (state.get("chat_summary") or "").strip() or "（无）"
    reply = await compressModel.ainvoke(
        [
            SystemMessage(content=COMPACT_PROMPT),
            HumanMessage(
                content=f"【已有摘要】\n{summary}\n\n"
                f"【新的对话】\n{render_history(dropped)}"
            ),
        ]
    )
    text = reply.content if isinstance(reply.content, str) else ""
    if not text.strip():
        return {}

    return {
        "chat_summary": text.strip(),
        "messages": [RemoveMessage(id=message.id) for message in dropped],
    }


def _compact_fallback(state, error=None):
    """压不动就算了：留着下一轮再压，这一轮该落库的已经落完了。"""
    return {}


# 模型掉线、超时都从 _compact_node 里冒出来。包一层重试，实在不行就当这轮没压过 ——
# 摘要只是省地方，不该让它把一整轮的成功收尾变成报错。
compact = with_retry_and_fallback(_compact_node, _compact_fallback)
