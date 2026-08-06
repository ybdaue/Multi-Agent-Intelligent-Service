import datetime

from langchain_core.messages import SystemMessage


def inject_current_date(state) -> dict:
    """中间件：每次 LLM 调用前注入当前日期到系统消息"""
    messages = list(state["messages"])
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %A")

    system_msg = SystemMessage(
        content=f"今天是 {date_str}。你是一个金融助手，可以使用工具查询 A 股数据。"
    )

    if messages and isinstance(messages[0], SystemMessage):
        messages[0] = system_msg
    else:
        messages.insert(0, system_msg)

    return {"messages": messages}
