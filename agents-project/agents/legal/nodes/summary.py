import uuid

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from ..state import State
from ..utils import model as models
from ..utils.prompts import SUMMARY_PROMPT
from ..utils.results import render_results_text


# 任务跑完后的收尾：用 CompressModel 生成一段完整最终答复
async def _summary_node(state: State, config: RunnableConfig):
    print("正在总结回复")
    if not bool((config or {}).get("configurable", {}).get("produce_summary")):
        return {}
    if not state.get("completed_tasks"):
        # 本轮没有完成任何任务（闲聊/能力咨询等）：不额外调用总结模型，assistant 答复即最终答复。
        # 不能用 analysis_result/output_file 是否为空判断——它们是跨轮残留的。
        return {}

    # 定位本轮终稿（最后一条无 tool_calls 的 AIMessage），生成总结后把它替换掉，
    # 避免"简短完成语 + 完整总结"重复入库/重复展示。
    target_id = None
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            target_id = msg.id
            break

    conv_lines = []
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            conv_lines.append(f"用户：{msg.content}")
        elif isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            if msg.content:
                conv_lines.append(f"助手：{msg.content}")

    prompt = SUMMARY_PROMPT.format(
        user_message=state.get("user_message", ""),
        result_text=render_results_text(state) or "（无）",
        conversation="\n".join(conv_lines) or "（无）",
    )

    summary_text = ""
    async for chunk in models._summarizer_model.astream(
        [SystemMessage(content=prompt)], config
    ):
        if isinstance(chunk.content, str) and chunk.content:
            summary_text += chunk.content
    summary_text = summary_text.strip() or "本轮任务已完成。"

    updates = []
    if target_id:
        updates.append(RemoveMessage(id=target_id))
    updates.append(AIMessage(content=summary_text, id=str(uuid.uuid4())))

    print("回复总结结束")
    return {"messages": updates}


def _summary_fallback(state, error=None):
    # 总结失败则保留 assistant 原答复，不阻塞会话
    print(f"[summary] 生成总结失败，保留原答复：{error}")
    return {}
