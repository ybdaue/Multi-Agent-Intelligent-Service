import hashlib
import json
import os
import uuid
from typing import Optional

from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from fastapi import APIRouter, HTTPException, Form, UploadFile, File

from agents import get_agent
from api.utils.db import pg_pool


router = APIRouter(prefix="/api/legal/agent", tags=["法律智能体"])

# 小于该阈值时把文件字节内联在请求里交给 agent；更大则只落库，由 preprocessing 查库取字节切片
_INLINE_FILE_LIMIT = 5 * 1024 * 1024


async def _store_upload(
    *,
    userId: int,
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
        await conn.execute(
            """
            INSERT INTO temp_file
                (id, "userId", "threadId", "fileHash", "originalName", "mimeType", "sizeBytes", data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT ("userId", "threadId", "fileHash") DO NOTHING
            RETURNING id
            """,
            (
                temp_file_id,
                str(userId),
                threadId,
                fileHash,
                originalName,
                mimeType,
                len(content),
                content,
            ),
        )
        row = await conn.fetchone()
        if row is None:
            # 同会话已上传过相同文件，取既有行 id
            await conn.execute(
                'SELECT id FROM temp_file WHERE "userId" = %s AND "threadId" = %s AND "fileHash" = %s',
                (str(userId), threadId, fileHash),
            )
            row = await conn.fetchone()
        await conn.commit()
    return row[0]


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


async def _prepare_input_state(
    *,
    userId: int,
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

        if len(content) <= _INLINE_FILE_LIMIT:
            # 小文件：字节内联交给 agent，由 preprocessing 切片入向量库
            input_state["file_source"] = {
                "type": "bytes",
                "suffix": suffix,
                "content": content,
                "file_id": file_id,
            }
        else:
            # 大文件：不占用请求内存，只传 temp_file 行 id，preprocessing 查库取字节后切片
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
    userId: int,
    threadId: Optional[str],
    text: str,
    file: Optional[UploadFile],
    produce_summary: bool = False,
) -> StreamingResponse:
    """按 agent 名称流式执行，SSE 事件与 /multiAgent 完全一致。"""
    if not text.strip():
        raise HTTPException(status_code=400, detail="至少上传一段文本")

    # threadId 可选：缺失/为空视为新会话，由后端生成唯一 id，经首个 SSE 事件回传给前端沿用
    tid = (threadId or "").strip() or uuid.uuid4().hex

    input_state = await _prepare_input_state(
        userId=userId, threadId=tid, text=text, file=file
    )
    config = {
        "configurable": {
            "thread_id": tid,
            "userId": userId,
            "produce_summary": produce_summary,
        }
    }

    async def event_stream():
        # 首个事件回传权威 threadId（已存在线程也 echo，幂等），前端据此绑定会话
        yield f"event: session\ndata: {json.dumps({'threadId': tid}, ensure_ascii=False)}\n\n"
        has_file = False
        streamed_any_token = False
        final_text = ""
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
                        path_str = output_file.get("content", "")
                        filename = (
                            os.path.basename(path_str)
                            if isinstance(path_str, str) else ""
                        )
                        if filename:
                            yield (
                                f"event: file_generated\n"
                                f"data: {json.dumps({'userId': userId, 'filename': filename})}\n\n"
                            )

            if streamed_any_token or has_file:
                yield f"event: done\ndata: {json.dumps({'message': 'ok'})}\n\n"
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
    userId: int,
    threadId: Optional[str] = Form(None),
    text: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    return await _stream_agent(
        agent_name="multiAgent",
        userId=userId,
        threadId=threadId,
        text=text,
        file=file,
        produce_summary=False,
    )


@router.post("/legalAgent")
async def call_legal_agent(
    userId: int,
    threadId: Optional[str] = Form(None),
    text: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    """直连 legal_agent 编排图：threadId 可选，缺失即新会话（后端生成并回传）。"""
    return await _stream_agent(
        agent_name="legalAgent",
        userId=userId,
        threadId=threadId,
        text=text,
        file=file,
        produce_summary=True,
    )


