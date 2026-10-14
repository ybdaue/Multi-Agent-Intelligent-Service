"""从对话里取"最后一条没有工具调用的助手回复"。"""
from langchain_core.messages import AIMessage


def last_reply(messages) -> str:
    """最后一条没有工具调用的助手回复 —— 写手的交稿 / planner 的任务卡 / 审查判词 / 闲聊答复都是它。"""
    for message in reversed(messages or []):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            content = message.content
            if isinstance(content, str) and content.strip():
                return content
    return ""