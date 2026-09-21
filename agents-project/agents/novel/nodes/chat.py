from langchain_core.messages import HumanMessage, SystemMessage

from ..state import State
from ..utils import chatModel, CHAT_PROMPT, recent_history


async def chat(state: State):
    user_message = state.get("user_message", "")
    history = recent_history(state.get("messages"), state.get("chat_summary") or "")
    system_content = f"""{CHAT_PROMPT}
            # 当前对话上下文
            对话历史（最新在最后）：
            {history}"""

    response = await chatModel.ainvoke(
        [SystemMessage(system_content), HumanMessage(user_message)]
    )
    return {"messages": [response]}
