from langchain_core.messages import AIMessage

from ..state import State


def use_child_agent(state: State):
    if state.get("error"):
        return END
    latest_message = state["messages"][-1]
    print("正在判断是否需要调用工具", latest_message)
    if isinstance(latest_message, AIMessage) and latest_message.tool_calls:
        return "child_agent"
    # 无工具调用即进入终局：由 summary 节点决定是否需要生成最终总结（produce_summary），
    # 否则为空操作直接落到 update。
    return "summary"


def route_after_checkin(state: State) -> str:
    """本轮没带文件（纯文本/闲聊）就跳过文件预处理节点，别让文件节点进入文本问答的关键路径。"""
    return "preprocessing" if state.get("file_source") else "Intent"


def route_after_intent(state: State) -> str:
    """意图识别失败（模型不可用等）直接结束，不继续执行 load_memory → assistant。"""
    return END if state.get("error") else "load_memory"
