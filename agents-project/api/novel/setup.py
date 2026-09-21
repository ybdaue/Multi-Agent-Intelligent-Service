"""开书 agent 的 HTTP 入口：只在「新建小说」弹窗里用。

一个 thread 就是一本待建的书，thread_id 取 novel_id（前端在弹窗打开时就生成好，与主图那本
书共用一个 id，但两边各自一个 checkpoint 名，快照不互相踩）。

一轮就是一次请求：模型把话说完（散文逐字下发），图停在 wait 上等答复（或六项齐了停在
confirm 上等过目）。interrupt 一来这一轮就结束了，所以流里要把「问题」交给前端；用户答了再走
/resume，同一个 thread_id，用 Command(resume=答复) 接着跑。认可之后 save 落库，final 带
saved=true，前端据此关窗、刷新书架。

事件只有 session / token / question / final / error / done：
  - token 只来自 collect（图里唯一开流式的模型；confirm 的 intentModel 关着流式），
    且内容全是散文 —— 标记块由 stream.SettingFilter 在它起点处截断。
  - 没有 stage，也没有 prose_start：一轮只有一次模型流，前端提交时自己挂一句"正在想…"。
"""
import json
import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk
from langgraph.types import Command

from agents.novel.setup import novel_setup_agent

from .stream import SettingFilter

router = APIRouter(prefix="/api/novel/setup", tags=["小说开书"])

logger = logging.getLogger(__name__)

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _event(name: str, payload: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chunk_text(chunk) -> str:
    """AIMessageChunk 的文本内容，字符串与分块两种形态都兜住。"""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _config(user_id: str, novel_id: str) -> dict:
    return {
        "configurable": {
            "thread_id": novel_id,
            "novel_id": novel_id,
            "user_id": user_id,
        },
        # 一轮只走 collect → wait 两步，用不到默认 25 那么多；interrupt 会结束这一轮，
        # 用户一轮轮作答不累积。留着是为了跟主图一个口径，回炉几次也不会撞上限。
        "recursion_limit": 80,
    }


def _final_payload(values: dict, novel_id: str) -> dict:
    """这一轮跑完（或停下）之后的响应体，从 checkpoint 快照取。

    停在 interrupt 上时，问题在这一版 langgraph 里 values 与 tasks[].interrupts 两处都可能是
    空的（实测如此），所以 `_sse` 那边还有一条从 updates 流里接的来路，两者谁先拿到算谁。
    """
    return {
        "saved": bool(values.get("saved")),
        "message": str(values.get("edit_note") or ""),
        "novelId": novel_id,
    }


async def _snapshot(user_id: str, novel_id: str) -> dict:
    """最新快照的 values，顺手把 interrupt 从 tasks 里捞回 __interrupt__ 上。"""
    snapshot = await novel_setup_agent.aget_state(_config(user_id, novel_id))
    values = dict(snapshot.values or {})
    if not values.get("__interrupt__"):
        for source in (
            getattr(snapshot, "interrupts", None),
            next(
                (
                    task.interrupts
                    for task in snapshot.tasks or ()
                    if getattr(task, "interrupts", None)
                ),
                None,
            ),
        ):
            if source:
                values["__interrupt__"] = source
                break
    return values


def _sse(*, user_id: str, novel_id: str, graph_input) -> StreamingResponse:
    """把一轮开书图跑成 SSE。"""

    async def event_stream():
        yield _event("session", {"threadId": novel_id})
        prose = SettingFilter()
        question = ""
        try:
            async for mode, data in novel_setup_agent.astream(
                graph_input, _config(user_id, novel_id), stream_mode=["messages", "updates"]
            ):
                if mode == "messages":
                    chunk, metadata = data
                    if not isinstance(chunk, AIMessageChunk):
                        continue
                    # 图里只有 collect 的模型开流式（confirm 的 intentModel 关着），这一行是
                    # 第二道保险。collect 是普通节点，metadata 里的节点名就是准的。
                    if (metadata or {}).get("langgraph_node") == "collect":
                        for name, payload in prose.feed(_chunk_text(chunk)):
                            yield _event(name, payload)
                elif mode == "updates":
                    for node, update in (data or {}).items():
                        # interrupt 只从这条流里接得到（快照的 tasks[].interrupts 是空的）
                        if node == "__interrupt__" and not question:
                            for item in update or ():
                                if getattr(item, "value", None):
                                    question = str(item.value)
                                    break

            for name, payload in prose.flush():
                yield _event(name, payload)

            # 停下来的问题：流里接到的与快照里的互为备份，谁有用谁。两处都空就是这一轮没停
            # （走到 save 收工），那不是错误，交给 final 说。**取 [0] 之前必须判空**。
            values = await _snapshot(user_id, novel_id)
            interrupts = values.get("__interrupt__") or ()
            first = interrupts[0] if interrupts else None
            text = str(getattr(first, "value", "") or question)
            if text:
                yield _event("question", {"text": text})
            else:
                yield _event("final", _final_payload(values, novel_id))
            yield _event("done", {})
        except Exception as e:  # 流已经开了，只能把错误当一条事件发出去
            # 前端只拿得到一句话，出了岔子得让服务端日志留住 traceback（否则无从下手）。
            logger.exception("开书这一轮跑挂了：novel=%s", novel_id)
            yield _event("error", {"message": str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/run")
async def run_setup(
    request: Request,
    novelId: str = Form(...),
    text: str = Form(...),
):
    """开书第一轮：弹窗里那句开场白（可以很模糊）交给开书图，流式跑，停在提问上。"""
    if not text.strip():
        raise HTTPException(status_code=400, detail="至少说一句想写什么")

    user_id = str(request.state.user_id)
    return _sse(
        user_id=user_id,
        novel_id=novelId,
        graph_input={"user_id": user_id, "user_message": text},
    )


@router.post("/resume")
async def resume_setup(
    request: Request,
    novelId: str = Form(...),
    answer: str = Form(...),
):
    """把用户对上一个问题的答复交回开书图，接着问下一项或请他过目 / 落库。"""
    if not answer.strip():
        raise HTTPException(status_code=400, detail="答复不能是空的")

    return _sse(
        user_id=str(request.state.user_id),
        novel_id=novelId,
        graph_input=Command(resume=answer),
    )
