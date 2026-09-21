import json
import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END
from langgraph.types import Command

from ..state import State
from ..utils import model as models
from ..utils.prompts import DECISION_PROMPT
from ..utils.results import TOOL_TO_TASK, extract_tool_results
from ..utils.streaming import invoke_assistant_model, stream_assistant_response


async def _assistant_node(state, config=None):
    print("法律assistant正在工作")
    # 提取最近一次工具执行结果到产物字段（会合并到返回值中）
    tool_result_updates = extract_tool_results(state)

    # 根据"本轮"最近执行的工具推导"已完成任务"：只认本轮（最后一条 HumanMessage 之后）
    # 产生的 ToolMessage，避免历史轮次的工具调用污染本轮的 completed_tasks
    all_msgs = state.get("messages", [])
    scan_from = 0
    for i in range(len(all_msgs) - 1, -1, -1):
        if isinstance(all_msgs[i], HumanMessage):
            scan_from = i + 1
            break
    completed_tasks = list(state.get("completed_tasks", []))
    last_tool_name = None
    for msg in reversed(all_msgs[scan_from:]):
        if isinstance(msg, ToolMessage) and msg.name in TOOL_TO_TASK:
            last_tool_name = msg.name
            break
    if last_tool_name:
        done_task = TOOL_TO_TASK[last_tool_name]
        if done_task not in completed_tasks:
            completed_tasks.append(done_task)

    pending_tasks = state.get("pending_tasks", [])
    remaining_tasks = [t for t in pending_tasks if t not in completed_tasks]
    next_task = remaining_tasks[0] if remaining_tasks else None

    print(f"[assistant] 已完成={completed_tasks} 剩余={remaining_tasks} 下一步={next_task} 最后工具={last_tool_name}")

    # 计算各产物状态文本
    file_status = "有" if (state.get("file_source") is not None or state.get("doc_ids")) else "无"
    has_analysis = tool_result_updates.get("analysis_result", state.get("analysis_result")) is not None
    analysis_status = "有" if has_analysis else "无"

    doc_ids = state.get("doc_ids", [])
    doc_id = doc_ids[0] if doc_ids else ""

    current_output_file = tool_result_updates.get("output_file", state.get("output_file"))
    draft_status = "有" if current_output_file else "无"
    output_file_path = current_output_file.get("filename", "") if current_output_file else ""

    task_context = state.get("task_context", {})
    task_context_str = json.dumps(task_context, ensure_ascii=False) if task_context else "无"

    # 从 checkpoint 持久化的 state["messages"] 中提取用户可见对话历史，用于指代消解
    all_messages = state.get("messages", [])
    conversation_pairs = []
    for msg in all_messages:
        if isinstance(msg, HumanMessage):
            conversation_pairs.append(f"用户：{msg.content}")
        elif isinstance(msg, AIMessage) and not (hasattr(msg, "tool_calls") and msg.tool_calls):
            if msg.content:
                conversation_pairs.append(f"助手：{msg.content}")

    # 最后一条 HumanMessage 是当前轮次，往前都是历史
    conversation_history_str = "\n".join(conversation_pairs[:-1]) if len(conversation_pairs) > 1 else "（无历史）"
    summary = (state.get("summary") or "").strip()
    if summary:
        conversation_history_str = f"【更早对话摘要】\n{summary}\n\n{conversation_history_str}"

    system_prompt = DECISION_PROMPT.format(
        last_user_message=state["user_message"],
        conversation_history=conversation_history_str,
        legal_domain="、".join(state.get("preference", [])) or "通用民事",
        task_context=task_context_str,
        step=state.get("step", 0),
        max_step=state.get("max_step", 10),
        pending_tasks=pending_tasks,
        completed_tasks=completed_tasks,
        remaining_tasks=remaining_tasks,
        next_task=next_task,
        doc_id=doc_id,
        file_status=file_status,
        analysis_status=analysis_status,
        draft_status=draft_status,
        output_file_path=output_file_path,
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=state["user_message"]),
    ]

    # ===== 硬停止：防止 assistant↔child_agent 无限循环 =====
    # 任务栈耗尽或总步骤超限时，不再调用模型，直接产出最终消息结束。
    step = state.get("step", 0)
    max_step = state.get("max_step", 10)

    tasks_done = bool(pending_tasks) and next_task is None
    if step >= max_step:
        stop_reason = "step"
    elif tasks_done:
        stop_reason = "done"
    else:
        stop_reason = None

    if stop_reason:
        if stop_reason == "done" and output_file_path:
            final_msg = f"任务已完成，已生成文书：{output_file_path}"
        elif stop_reason == "done":
            final_msg = "本轮任务已完成。"
        else:
            final_msg = "本轮处理步骤已达上限，为避免重复处理已自动结束。"
        # 显式分配 id：produce_summary 模式下 summary 节点按 id 移除本条简短的终稿
        return {
            "messages": [AIMessage(content=final_msg, id=str(uuid.uuid4()))],
            "step": step,
            "completed_tasks": completed_tasks,
            **tool_result_updates,
        }

    # 无待办任务（闲聊/能力咨询）：不绑工具、输出即最终答复，可以流式直答。
    # 有待办任务：改非流式，避免工具调用前的寒暄混进前端答复（见 invoke_assistant_model）。
    if pending_tasks:
        response = await invoke_assistant_model(models.model, messages, config)
    else:
        response = await stream_assistant_response(
            models.MainModel(temperature=0.5), messages, config
        )

    # 强制每轮只调一个工具：并行调用会破坏任务先后依赖，只保留第一个，剩余丢弃
    if hasattr(response, "tool_calls") and len(response.tool_calls) > 1:
        response = AIMessage(
            content=response.content,
            tool_calls=[response.tool_calls[0]],
            id=response.id,
        )

    # 模型若试图重复执行已完成的任务，重罚 step 加快触顶兜底（正常模型不应走到这里）
    repeated = False
    if hasattr(response, "tool_calls") and response.tool_calls:
        tool_name = response.tool_calls[0].get("name") or response.tool_calls[0]["name"]
        if TOOL_TO_TASK.get(tool_name) in completed_tasks:
            repeated = True

    tool_count = 1 if (hasattr(response, "tool_calls") and response.tool_calls) else 0
    return {
        "messages": [response],
        "step": step + (2 if repeated else tool_count),
        "completed_tasks": completed_tasks,
        **tool_result_updates,
    }


def _assistant_fallback(state, error=None):
    tool_result_updates = extract_tool_results(state)
    return Command(
        update={
            "error": f"调度模型服务不可用：{error}",
            "messages": [AIMessage(content="抱歉，服务暂时不可用，请稍后再试。")],
            **tool_result_updates,
        },
        goto=END
    )
