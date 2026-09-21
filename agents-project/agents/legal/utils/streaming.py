import json
import uuid

from langchain_core.messages import AIMessage


async def stream_assistant_response(llm, messages, config):
    """流式累积 LLM 输出为完整 AIMessage（含 tool_calls）。

    config 必须透传给 llm.astream：由 graph 运行上下文把 token 回调灌进本次调用，
    从而让外部 .astream(stream_mode="messages") 能逐 token 拿到内容。
    """
    full_content = ""
    tool_call_chunks_acc = []
    response_id = None

    async for chunk in llm.astream(messages, config):
        if response_id is None and getattr(chunk, "id", None):
            response_id = chunk.id
        if isinstance(chunk.content, str) and chunk.content:
            full_content += chunk.content
        if chunk.tool_call_chunks:
            tool_call_chunks_acc.extend(chunk.tool_call_chunks)

    final_id = response_id or str(uuid.uuid4())

    if tool_call_chunks_acc:
        merged = {}
        for tcc in tool_call_chunks_acc:
            idx = tcc.get("index", 0)
            if idx not in merged:
                merged[idx] = {"name": "", "args": "", "id": ""}
            merged[idx]["name"] += tcc.get("name") or ""
            merged[idx]["args"] += tcc.get("args") or ""
            merged[idx]["id"] += tcc.get("id") or ""

        tool_calls = []
        for idx in sorted(merged.keys()):
            mc = merged[idx]
            try:
                args = json.loads(mc["args"]) if mc["args"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"name": mc["name"], "args": args, "id": mc["id"]})
        return AIMessage(content="", tool_calls=tool_calls, id=final_id)

    return AIMessage(content=full_content, id=final_id)


async def invoke_assistant_model(llm, messages, config):
    """非流式调用调度模型（有待办任务的轮次用）。

    这类轮次模型可能先吐一句寒暄再发起工具调用，而寒暄会被丢弃、不进 state；
    若走流式，寒暄的分片已经下发到前端，就成了回复里的杂项。改非流式后，
    用户可见的最终答复统一由 summary 节点流式输出。
    """
    response = await llm.ainvoke(messages, config)
    if not getattr(response, "id", None):
        response = response.model_copy(update={"id": str(uuid.uuid4())})
    return response
