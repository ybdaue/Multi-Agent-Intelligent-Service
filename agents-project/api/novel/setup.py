"""开书 agent 的 HTTP 入口：只在「新建小说」弹窗里用。

一个 thread 就是一本待建的书，thread_id 取 novel_id（前端在弹窗打开时就生成好，与主图那本
书共用一个 id，但两边各自一个 checkpoint 名，快照不互相踩）。

一轮就是一次请求：discuss 节点流式生成问题，停在 interrupt 上等答复。用户答了走 /resume，
同一条 thread_id 用 Command(resume=答复) 接着跑。每一步：用户答 → maintain 提取 →
discuss 再问下一项（流式），直至六项齐了 → confirm 过目 → save 落库。final 带 saved=true，
前端据此关窗、刷新书架。

事件只有 session / token / question / final / error / done：
  - token 来自 discuss 节点（图里唯一开流式的模型），内容全是散文。
  - 没有 stage，也没有 prose_start：一轮只有一次模型流，前端提交时自己挂一句"正在想…"。
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk
from langgraph.types import Command

from agents.novel.setup import novel_setup_agent

from ..utils.sse import HEARTBEAT, with_heartbeat

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


def _config(user_id: str, novel_id: str, callbacks: Optional[list] = None) -> dict:
    return {
        "callbacks": callbacks,
        "configurable": {
            "thread_id": novel_id,
            "novel_id": novel_id,
            "user_id": user_id,
        },
        # greeting → discuss → maintain → ... 循环，用不到默认 25 那么多；
        # interrupt 会结束这一轮，用户一轮轮作答不累积。
        # 留着是为了跟主图一个口径，回炉几次也不会撞上限。
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


def _sse(*, user_id: str, novel_id: str, graph_input, callbacks: Optional[list] = None) -> StreamingResponse:
    """把一轮开书图跑成 SSE。"""
    async def event_stream():
        yield _event("session", {"threadId": novel_id})
        replayed = True
        question = ""
        saved = False
        edit_note = ""
        try:
            events = novel_setup_agent.astream(
                graph_input, _config(user_id, novel_id, callbacks), stream_mode=["messages", "updates"],
                subgraphs=True,
            )
            async for item in with_heartbeat(events, label="setup"):
                if item is None:
                    # 图闷住了（maintain 这类不流式的节点可能在跑），发一行注释把连接
                    # 的"空闲"消掉，免得中间代理按读超时把流掐了。
                    yield HEARTBEAT
                    continue
                namespace, mode, data = item
                if mode == "messages":
                    if replayed:
                        continue
                    chunk, metadata = data
                    if not isinstance(chunk, AIMessageChunk):
                        continue
                    meta = metadata or {}
                    node = str(meta.get("langgraph_node") or "")
                    if node == "discuss":
                        text = _chunk_text(chunk)
                        if text:
                            yield _event("token", {"text": text})
                elif mode == "updates":
                    for node, update in (data or {}).items():
                        if node == "__interrupt__":
                            # Resume 时可能有重放过来的旧 interrupt，但最新的 interrupt 一定来自
                            # 当前真正执行的节点（ask_user），后面会覆盖前面，最终值就是正确的。
                            for item in update or ():
                                if getattr(item, "value", None):
                                    question = str(item.value)
                                    break
                        elif node == "save":
                            if isinstance(update, dict):
                                if update.get("saved"):
                                    saved = True
                                if update.get("edit_note"):
                                    edit_note = str(update["edit_note"])
                        else:
                            replayed = False

            # 优先用流里捕获的 save 节点返回值（比 snapshot 更即时）
            if saved:
                yield _event("final", {"saved": True, "message": edit_note, "novelId": novel_id})
            else:
                # 回退到 snapshot（权威来源）
                values = await _snapshot(user_id, novel_id)
                interrupts = values.get("__interrupt__") or ()
                first = interrupts[0] if interrupts else None
                if first:
                    yield _event("question", {"text": str(getattr(first, "value", ""))})
                elif question:
                    # snapshot 没取到但流里捕获了（LangGraph 版本差异），直接用它
                    yield _event("question", {"text": question})
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
    handler = getattr(request.state, "token_collector", None)
    return _sse(
        user_id=user_id,
        novel_id=novelId,
        graph_input={"user_id": user_id, "user_message": text},
        callbacks=[handler] if handler else None,
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

    user_id = str(request.state.user_id)
    handler = getattr(request.state, "token_collector", None)
    return _sse(
        user_id=user_id,
        novel_id=novelId,
        graph_input=Command(resume=answer),
        callbacks=[handler] if handler else None,
    )


@router.get("/settings")
async def get_setup_settings(
    request: Request,
    novelId: str = "",
):
    """返回开书图的设定收集状态（从 checkpoint 读取，不修改任何数据）。

    前端右侧面板用它渲染和刷新。checkpoint 还没建起来时返回全空状态 —— 不报错，不打断用户。
    """
    from agents.novel.setup.settings import (
        DEPENDENCIES,
        SETTING_FIELDS,
        SETTING_LABELS,
        get_sub_field_status,
        render_item,
    )

    if not novelId.strip():
        raise HTTPException(status_code=400, detail="缺少小说 id")

    user_id = str(request.state.user_id)
    try:
        snapshot = await novel_setup_agent.aget_state(_config(user_id, novelId))
        values = dict(snapshot.values or {})
        settings = values.get("settings") or {}
    except Exception:
        settings = {}

    fields = []
    for f in SETTING_FIELDS:
        raw = settings.get(f)
        collected = bool(raw)
        content = render_item(f, raw) if collected else ""
        # 子字段清单始终返回（未收集时全为 False），让面板能一直展示"要收集哪些子项"
        sub_fields = get_sub_field_status(f, raw)
        entry = {
            "field": f,
            "label": SETTING_LABELS.get(f, f),
            "content": content,
            "collected": collected,
        }
        if sub_fields:
            entry["sub_fields"] = sub_fields
        fields.append(entry)

    return {
        "fields": fields,
        "dependencies": dict(DEPENDENCIES),
    }
