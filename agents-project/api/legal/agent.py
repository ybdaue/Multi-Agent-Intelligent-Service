import hashlib
import json
import os
import uuid
from typing import Optional

from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from fastapi import APIRouter, HTTPException, Request, Form, UploadFile, File

from agents import get_agent
from api.utils.db import pg_pool


router = APIRouter(prefix="/api/legal/agent", tags=["法律智能体"])


async def _store_upload(
    *,
    userId: str,
    threadId: str,
    originalName: str,
    mimeType: str,
    fileHash: str,
    content: bytes,
) -> str:
    """用户上传文件落库 temp_file（7 天过期）。

    同一会话(userId+threadId)内相同内容(fileHash)只保留一行：冲突时复用既有行，
    不同会话之间允许各自保留副本。
    """
    temp_file_id = uuid.uuid4().hex
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            """
            INSERT INTO temp_file
                (id, "userId", "threadId", "fileHash", "originalName", "mimeType", "sizeBytes", data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT ("userId", "threadId", "fileHash") DO NOTHING
            RETURNING id
            """,
            (
                temp_file_id,
                userId,
                threadId,
                fileHash,
                originalName,
                mimeType,
                len(content),
                content,
            ),
        )
        row = await cur.fetchone()
        if row is None:
            # 同会话已上传过相同文件，取既有行 id
            cur = await conn.execute(
                'SELECT id FROM temp_file WHERE "userId" = %s AND "threadId" = %s AND "fileHash" = %s',
                (userId, threadId, fileHash),
            )
            row = await cur.fetchone()
        await conn.commit()
    return row[0]


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


async def _prepare_input_state(
    *,
    userId: str,
    threadId: str,
    text: str,
    file: Optional[UploadFile],
) -> dict:
    input_state = {
        "messages": [HumanMessage(text)],
        "userId": userId,
        "user_message": text,
    }

    if file is not None:
        content = await file.read()
        # 用内容哈希作为 file_id：同一文件重复上传得到相同 id，Chroma upsert 原地覆盖，不产生重复切片
        file_id = hashlib.md5(content).hexdigest()
        suffix = os.path.splitext(file.filename or "")[1]

        # 无论文件大小，原始字节一律落库 temp_file（7 天过期）；同会话相同文件由唯一键去重
        temp_file_id = await _store_upload(
            userId=userId,
            threadId=threadId,
            originalName=file.filename or "upload",
            mimeType=file.content_type or "application/octet-stream",
            fileHash=file_id,
            content=content,
        )

        # 一律只传 temp_file 行 id，由 preprocessing 查库取字节后切片。
        # 不把字节内联进 state：state 每个超级步都会整份写入 checkpoint 快照，
        # 内联会让单个快照膨胀到 MB 级，并随快照组一起长期留存。
        input_state["file_source"] = {
            "type": "db",
            "suffix": suffix,
            "content": temp_file_id,
            "file_id": file_id,
        }
    else:
        input_state["file_source"] = None

    return input_state


async def _stream_agent(
    *,
    agent_name: str,
    userId: str,
    threadId: Optional[str],
    text: str,
    file: Optional[UploadFile],
    produce_summary: bool = False,
    answer_nodes: Optional[set[str]] = None,
    callbacks: Optional[list] = None,
) -> StreamingResponse:
    """按 agent 名称流式执行，SSE 事件与 /multiAgent 完全一致。

    answer_nodes 非空时只放行这些节点产生的 token（用户可见的最终答复），
    其余节点（意图识别、调度、子 Agent 内部推理等）的输出一律不下发。
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="至少上传一段文本")

    # threadId 自带归属：新会话由后端生成 "{userId}:{hex}"；客户端传回的一律校验前缀，
    # 不匹配即拒绝 —— 归属是结构性的，即使将来某条 SQL 漏了 userId 过滤也跨不过去
    supplied = (threadId or "").strip()
    if supplied and not supplied.startswith(f"{userId}:"):
        raise HTTPException(status_code=403, detail="会话不属于当前用户")
    tid = supplied or f"{userId}:{uuid.uuid4().hex}"

    input_state = await _prepare_input_state(
        userId=userId, threadId=tid, text=text, file=file
    )
    config = {
        "callbacks": callbacks,
        "configurable": {
            "thread_id": tid,
            "userId": userId,
            "produce_summary": produce_summary,
        },
    }

    async def event_stream():
        # 首个事件回传权威 threadId（已存在线程也 echo，幂等），前端据此绑定会话
        yield f"event: session\ndata: {json.dumps({'threadId': tid}, ensure_ascii=False)}\n\n"
        has_file = False
        streamed_any_token = False
        final_text = ""
        has_error = False
        try:
            async for event in get_agent(agent_name).astream(
                input_state, config, stream_mode=["messages", "values"]
            ):
                if not isinstance(event, tuple) or len(event) != 2:
                    continue

                mode, data = event

                if mode == "messages":
                    msg, metadata = data
                    if not isinstance(msg, AIMessageChunk):
                        continue
                    if (
                        answer_nodes is not None
                        and metadata.get("langgraph_node") not in answer_nodes
                    ):
                        # 非最终答复节点（意图/调度/子 Agent）的 token 一律丢弃
                        continue
                    content = msg.content
                    if isinstance(content, str) and content:
                        streamed_any_token = True
                        yield (
                            f"event: token\n"
                            f"data: {json.dumps({'text': content}, ensure_ascii=False)}\n\n"
                        )
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text" and c["text"]:
                                streamed_any_token = True
                                yield (
                                    f"event: token\n"
                                    f"data: {json.dumps({'text': c['text']}, ensure_ascii=False)}\n\n"
                                )

                elif mode == "values":
                    state = data
                    # 图中某节点出错（意图识别/模型调用等 fallback）：只发送一次 error 事件，不走 final_text
                    if state.get("error") and not has_error:
                        has_error = True
                        for m in reversed(state.get("messages") or []):
                            if (
                                isinstance(m, AIMessage)
                                and not getattr(m, "tool_calls", None)
                                and getattr(m, "content", None)
                            ):
                                content = m.content
                                if isinstance(content, str) and content:
                                    yield (
                                        f"event: error\n"
                                        f"data: {json.dumps({'message': content}, ensure_ascii=False)}\n\n"
                                    )
                                break
                        continue

                    # 记录最终答复文本做兜底：偶发轮次全程无 token（如纯规则终稿）时，
                    # 仍把最后一条助手文本一次性补发给前端，避免误报"流式传输失败"
                    for m in reversed(state.get("messages") or []):
                        if (
                            isinstance(m, AIMessage)
                            and not getattr(m, "tool_calls", None)
                            and getattr(m, "content", None)
                        ):
                            content = m.content
                            if isinstance(content, str) and content:
                                final_text = content
                            break

                    output_file = state.get("output_file")
                    if output_file and not has_file:
                        has_file = True
                        file_id = output_file.get("content", "")
                        filename = output_file.get("filename", "")
                        if file_id and filename:
                            yield (
                                f"event: file_generated\n"
                                f"data: {json.dumps({'fileId': file_id, 'filename': filename}, ensure_ascii=False)}\n\n"
                            )

            if streamed_any_token or has_file:
                yield f"event: done\ndata: {json.dumps({'message': 'ok'})}\n\n"
            elif has_error:
                yield f"event: done\ndata: {json.dumps({'message': 'error_sent'})}\n\n"
            elif final_text:
                yield (
                    f"event: token\n"
                    f"data: {json.dumps({'text': final_text}, ensure_ascii=False)}\n\n"
                )
                yield f"event: done\ndata: {json.dumps({'message': 'ok'})}\n\n"
            else:
                yield (
                    f"event: error\n"
                    f"data: {json.dumps({'message': '后端未返回流式内容，流式传输失败'})}\n\n"
                )

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/multiAgent")
async def call_agent(
    request: Request,
    threadId: Optional[str] = Form(None),
    text: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    handler = getattr(request.state, "token_collector", None)
    return await _stream_agent(
        agent_name="multiAgent",
        userId=request.state.user_id,
        threadId=threadId,
        text=text,
        file=file,
        produce_summary=False,
        callbacks=[handler] if handler else None,
    )


@router.post("/legalAgent")
async def call_legal_agent(
    request: Request,
    threadId: Optional[str] = Form(None),
    text: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    """直连 legal_agent 编排图：threadId 可选，缺失即新会话（后端生成并回传）。

    userId 由全局 auth 中间件从 Bearer token 解析后写入 request.state（better-auth 的 cuid），
    不再由前端 query 传入 —— 它就是 checkpoint / agent_store / user_session / temp_file 的隔离 key。
    """
    handler = getattr(request.state, "token_collector", None)
    return await _stream_agent(
        agent_name="legalAgent",
        userId=request.state.user_id,
        threadId=threadId,
        text=text,
        file=file,
        produce_summary=True,
        # legal 图的用户可见输出：assistant 出纯闲聊答复，summary 出任务终稿
        answer_nodes={"assistant", "summary"},
        callbacks=[handler] if handler else None,
    )


