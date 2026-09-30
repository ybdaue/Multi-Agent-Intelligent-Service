import json
import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..state import State
from ..utils import model as models
from ..utils.prompts import INTENT_PROMPT

VALID_INTENTS = {"draft", "analyze", "consult", "chat"}


async def _intent_node(state, config=None):
    user_msg = state["user_message"]

    # ===== 组装对话上下文：文件状态 + 对话历史 =====
    has_file = state.get("file_source") is not None or bool(state.get("doc_ids"))
    file_status = "用户已上传文件（可对其进行分析/审查）" if has_file else "用户未上传文件"

    all_messages = state.get("messages", [])
    conv_lines = []
    for m in all_messages:
        if isinstance(m, HumanMessage):
            conv_lines.append(f"用户：{m.content}")
        elif isinstance(m, AIMessage) and not (hasattr(m, "tool_calls") and m.tool_calls):
            if m.content:
                conv_lines.append(f"助手：{m.content}")
    history_str = "\n".join(conv_lines[:-1]) if len(conv_lines) > 1 else "（无历史）"
    summary = (state.get("summary") or "").strip()
    if summary:
        history_str = f"【更早对话摘要】\n{summary}\n\n{history_str}"

    system_content = f"""{INTENT_PROMPT}
        # 当前对话上下文（识别意图时必须结合）
        文件状态：{file_status}
        对话历史（最新在最后）：
        {history_str}"""

    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_msg),
    ]
    # 必须 async/await：with_retry_and_fallback 本身是 async 节点（跑在事件循环上），
    # 同步 invoke 会把这整段 HTTP 调用内联到 loop 上，卡住所有并发请求。
    # Intent_model 实例已设 disable_streaming=True，意图 JSON 不会作为 token 下发。
    try:
        response = await models.Intent_model.ainvoke(messages)
    except Exception:
        try:
            response = await models.Intent_model_backup.ainvoke(messages)
        except Exception:
            raise
    try:
        parsed = json.loads(response.content)
        print("识别到用户意图", user_msg, parsed)
    except json.JSONDecodeError:
        parsed = {}

    intent = parsed.get("primary_intent")
    if intent not in VALID_INTENTS:
        # 未能识别出有效意图：不做关键词猜测，直接结束并告知用户
        # （条件边 route_after_intent 检测到 error 后路由到 END）
        return {
            "error": "意图识别结果为空",
            "messages": [
                AIMessage(
                    content="抱歉，我没能理解您的需求。请把想做的法律事项描述得更具体一些，"
                    "例如让我审查合同、解释违约金，或起草一份劳动合同。"
                )
            ],
        }

    return {
        "primary_intent": intent,
        "pending_tasks": parsed.get("pending_tasks", []),
        "task_context": parsed.get("task_context", {}),
        "trace_id": str(uuid.uuid4()),
        "step": 0,
        "completed_tasks": [],
    }


def _intent_fallback(state, error=None):
    return {
        "error": f"意图识别服务不可用：{error}",
        "messages": [AIMessage(content="抱歉，意图识别服务暂时不可用，请稍后再试。")],
    }
