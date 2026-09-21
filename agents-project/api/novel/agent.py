"""小说智能体的 HTTP 入口。

一个 thread 就是一本小说，所以 config 里的 thread_id 直接取 novel_id —— LangGraph 挂了
checkpointer 就必须有这个键，在这一层派生，调用方只管传 user_id / novel_id / chapter_id。
chapter_id 只服务于"改已有章节正文"这一路：intension 在识别出"改"之后拿它钉住用户这会儿开着
的那一章 —— 用户开着哪一章只有请求知道，模型看不见（见 agents/novel/nodes/intension.py）。
拦截发生在 editor.plan：确认要改的确实是章节正文、又发现他话里点的章跟钉住的这一章对不上，
才回一句请他先切过去。写新章由 writer 按库里 MAX(order)+1 定序号，改设定挂在书上，两条路都
不看 chapterId。本地新建、还没落库的章解析不出来，就当没钉住，改正文时直接拒不动手。

图里有两条路会停下来等用户：reader 审完之后的 confirm_chapter、editor 改设定之前的 approve。
interrupt 一来这一轮就结束了，所以流里要把「问题」交给前端；用户答了再走 /resume，同一个
thread_id，用 Command(resume=答复) 接着跑。

开书（把一本书的设定从零问齐、落库）不在这个图里：那是「新建小说」弹窗专用的独立图，
见 api/novel/setup.py。这里碰到库里没有的书，只回一句让用户去弹窗建。

/run 与 /resume 走 SSE：writer / editor 的正文逐字下发，台账一个字不露（见 stream.py 的
ProseFilter）。run_novel / resume_novel 那两条非流式入口留着，测试与脚本直接调它们。
"""
import json
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk
from langgraph.types import Command

from agents.novel import novel_agent

from .stream import ProseFilter

router = APIRouter(prefix="/api/novel/agent", tags=["小说智能体"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# 状态行文案：按父图的节点名报，不读任何模型输出 —— reader 的判词 JSON、summarize 的摘要
# 都不可能从这里漏出去。没列进来的节点（以及子图内部的 model / tools）一律不报。
# 报的时机在 tasks 流上：任务**开跑**就报（updates 那条流要等节点跑完才来，写一章的过程里
# 状态行会一直停在"正在读取这本书的设定…"）。
_STAGE_TEXT = {
    "intension": "正在理解你的需求…",
    "load": "正在读取这本书的设定…",
    "writer": "正在写这一章…",
    "reader": "正在审稿…",
    "confirm_chapter": "等你看这一稿…",
    "editor": "正在改这一章…",
    "update": "正在落库…",
    "compact": "正在整理对话…",
    "chat": "正在回复…",
}


def _event(name: str, payload: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _owner(metadata: dict) -> str:
    """这条 token 出自哪条路。

    metadata["langgraph_node"] 报的是当前执行层的节点名，writer / editor 内部用的是
    create_agent，那两层的节点都叫 model / tools，靠它分不出是谁。父图节点名只体现在
    checkpoint_ns 的首段（形如 writer:<uuid>|write:<uuid>|model:<uuid>）。
    """
    ns = (metadata or {}).get("langgraph_checkpoint_ns") or ""
    return ns.split("|")[0].split(":")[0]


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


def _config(user_id: str, novel_id: str, chapter_id: str = "") -> dict:
    return {
        "configurable": {
            "thread_id": novel_id,
            "novel_id": novel_id,
            "user_id": user_id,
            "chapter_id": chapter_id,
        },
        # 默认 25 是整轮共享的预算：父图节点和子图内部步数一起算。writer 一轮约 10 步，
        # 内部字数回炉、reader 打回各几次就逼近上限，到顶是 GraphRecursionError 把整轮跑崩，
        # 不是优雅收尾。interrupt 会结束这一轮，所以用户一轮轮作答不会累积到它头上。
        "recursion_limit": 80,
    }


def _reply(result: dict) -> str:
    """图这一轮最后写给用户的一句话。

    update 收尾时把"没听懂要改哪一处""这一章已改好"这类话写成 AIMessage 留在 state 里，
    前端得看得到它 —— 只给章节字段的话，那些没写成章节的一轮（闲聊、没改成的稿）就没有回话。
    """
    for message in reversed(result.get("messages") or []):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            content = message.content
            if isinstance(content, str) and content.strip():
                return content
    return ""


def _payload(result: dict) -> dict:
    """把图的结果折成响应体。停在 interrupt 上就把问题交回前端，否则给这一章的字段。"""
    interrupts = result.get("__interrupt__")
    if interrupts:
        return {"interrupted": True, "question": interrupts[0].value}

    chapter = result.get("active_chapter") or {}
    return {
        "interrupted": False,
        "message": _reply(result),
        "intension": result.get("intension"),
        "chapterId": chapter.get("chapter_id") or "",
        "chapterTitle": chapter.get("chapter_title") or "",
        "chapterOrder": chapter.get("chapter_order"),
        "chapterWordCount": chapter.get("chapter_word_count") or 0,
        "summary": chapter.get("chapter_summary") or "",
    }


async def run_novel(
    *,
    user_id: str,
    novel_id: str,
    chapter_id: str = "",
    message: str,
) -> dict:
    """跑一轮小说图。

    user_id 是 better-auth 的 cuid；novel_id 既是这本书的 id 也是 thread id。
    """
    result = await novel_agent.ainvoke(
        {"user_id": user_id, "user_message": message},
        _config(user_id, novel_id, chapter_id),
    )
    return _payload(result)


async def resume_novel(
    *,
    user_id: str,
    novel_id: str,
    answer: str,
    chapter_id: str = "",
) -> dict:
    """用户答了图停下来的那个问题，从停下的那一步接着跑。

    resume 必须落在同一个 thread 上，所以 config 与 /run 一模一样。
    """
    result = await novel_agent.ainvoke(
        Command(resume=answer),
        _config(user_id, novel_id, chapter_id),
    )
    return _payload(result)


async def _final_payload(user_id: str, novel_id: str, chapter_id: str) -> dict:
    """这一轮跑完（或停下）之后的响应体，从 checkpoint 快照取。

    停在 interrupt 上时，问题在这一版 langgraph 里 values 与 tasks[].interrupts 两处都可能是
    空的（实测如此），所以 `_sse` 那边还有一条从 updates 流里接的来路，两者谁先拿到算谁。
    """
    snapshot = await novel_agent.aget_state(_config(user_id, novel_id, chapter_id))
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
    return _payload(values)


def _sse(*, user_id: str, novel_id: str, chapter_id: str, graph_input) -> StreamingResponse:
    """把一轮图跑成 SSE。

    事件：session / stage / prose_start / token / question / final / error / done。
    prose_start 表示"正文从头开始"（回炉重写也发一次，前端据此清空临时框），token 只出现在
    prose_start 之后、内容全是正文。

    **必须 subgraphs=True**：writer / editor 是编译好的子图，langgraph 在 subgraphs=False 时
    直接丢掉子图里模型的 token（pregel/_messages.py 的 on_chat_model_start），正文会一个字都
    流不出来。代价是事件的形状变成三元组 (ns, mode, data)，ns 是所在的子图路径。

    三条流各司其职：messages 出正文 token，tasks 出状态行（任务开跑就报），updates 接
    interrupt（只有它接得到）。
    """
    config = _config(user_id, novel_id, chapter_id)

    async def event_stream():
        yield _event("session", {"threadId": novel_id})
        prose = ProseFilter()
        question = ""
        try:
            async for ns, mode, data in novel_agent.astream(
                graph_input,
                config,
                stream_mode=["messages", "tasks", "updates"],
                subgraphs=True,
            ):
                if mode == "messages":
                    chunk, metadata = data
                    if not isinstance(chunk, AIMessageChunk):
                        continue
                    # 只有 writer / editor 的 token 是正文；其余节点（reader、summarize）
                    # 的模型本来就关了流式，这里是第二道保险。
                    if _owner(metadata) in ("writer", "editor"):
                        for name, payload in prose.feed(_chunk_text(chunk)):
                            yield _event(name, payload)
                elif mode == "tasks":
                    # 状态行在任务**开跑**时报。带 triggers 的是开始事件，带 result 的是结束。
                    # 子图内部的任务不报（ns 非空，那些是 prepare / write / model），
                    # 用户认得的步骤只有父图这几个节点。
                    if not ns and isinstance(data, dict) and "triggers" in data:
                        if text := _STAGE_TEXT.get(str(data.get("name") or "")):
                            yield _event("stage", {"text": text})
                elif mode == "updates":
                    for node, update in (data or {}).items():
                        if node == "__interrupt__":
                            # interrupt 只从这条流里接得到（快照的 tasks[].interrupts 是空的）
                            if not question:
                                for item in update or ():
                                    if getattr(item, "value", None):
                                        question = str(item.value)
                                        break
                            continue
                        # 状态行兜底那一道：父图节点跑完再报一次同样的文案（tasks 那条流已经
                        # 在开跑时报过了，文字一模一样，前端换一遍而已）。子图内部的不报。
                        if not ns and (text := _STAGE_TEXT.get(node)):
                            yield _event("stage", {"text": text})

            for name, payload in prose.flush():
                yield _event(name, payload)

            # 停下来的问题：流里接到的与快照里的互为备份，谁有用谁。
            final = await _final_payload(user_id, novel_id, chapter_id)
            if not final.get("interrupted") and question:
                final = {"interrupted": True, "question": question}
            if final.get("interrupted"):
                yield _event("question", {"text": final.get("question") or question})
            else:
                yield _event("final", final)
            yield _event("done", {})
        except Exception as e:  # 流已经开了，只能把错误当一条事件发出去
            yield _event("error", {"message": str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/run")
async def call_novel_agent(
    request: Request,
    novelId: str = Form(...),
    text: str = Form(...),
    chapterId: Optional[str] = Form(None),
):
    """把一句话交给小说图，流式跑这一轮；停在提问上就把问题交给前端。

    开书不走这里（那是弹窗专用的 api/novel/setup.py）：库里没有这本书时，load 会回一句
    引导用户去弹窗建。
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="至少说一句要写什么")

    user_id = str(request.state.user_id)
    return _sse(
        user_id=user_id,
        novel_id=novelId,
        chapter_id=chapterId or "",
        graph_input={"user_id": user_id, "user_message": text},
    )


@router.post("/resume")
async def resume_novel_agent(
    request: Request,
    novelId: str = Form(...),
    answer: str = Form(...),
    chapterId: Optional[str] = Form(None),
):
    """把用户对上一个问题的答复交回图里，接着跑到下一个问题或本轮结束。"""
    if not answer.strip():
        raise HTTPException(status_code=400, detail="答复不能是空的")

    return _sse(
        user_id=str(request.state.user_id),
        novel_id=novelId,
        chapter_id=chapterId or "",
        graph_input=Command(resume=answer),
    )
