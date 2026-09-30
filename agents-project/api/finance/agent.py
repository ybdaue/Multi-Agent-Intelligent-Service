import asyncio
import json
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents import get_agent

router = APIRouter(prefix="/api/finance/agent", tags=["金融智能体"])

_agent = None
_agent_err = ""
try:
    _agent = get_agent("finance")
except RuntimeError as e:
    _agent_err = str(e)

_STREAM_TIMEOUT = 120


async def _error_stream(msg: str):
    yield f"data: {json.dumps({'error': msg})}\n\n"
    yield f"data: {json.dumps({'done': True})}\n\n"


class QueryRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None


class QueryResponse(BaseModel):
    response: str
    thread_id: str


@router.post("/query", response_model=QueryResponse)
async def query_agent(req: QueryRequest):
    if _agent is None:
        raise HTTPException(status_code=503, detail=_agent_err)
    try:
        tid = req.thread_id or str(uuid4())
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _agent.run, req.message, tid),
            timeout=_STREAM_TIMEOUT,
        )
        return QueryResponse(response=result, thread_id=tid)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="智能体响应超时")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def stream_agent(req: QueryRequest):
    if _agent is None:
        return StreamingResponse(
            _error_stream("金融服务暂不可用：" + _agent_err),
            media_type="text/event-stream",
        )
    tid = req.thread_id or str(uuid4())

    async def generate():
        try:
            ait = _agent.stream(req.message, thread_id=tid).__aiter__()
            while True:
                try:
                    token = await asyncio.wait_for(
                        ait.__anext__(), timeout=_STREAM_TIMEOUT
                    )
                    yield f"data: {json.dumps({'token': token})}\n\n"
                except StopAsyncIteration:
                    break
            yield f"data: {json.dumps({'thread_id': tid})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'error': '智能体响应超时'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
