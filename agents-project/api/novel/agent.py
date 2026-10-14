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

停在确认上的那一稿只活在 checkpoint 里（书架列表里没有它），而正文一落库就从快照里抹掉了 ——
所以"交上来、还没确认"这件事只能问快照：GET /pending 就是这个问法，前端刷新 / 切书时拿它
重建现场；/run 也拿它当门禁，免得用户没答上一稿又开新章、正文被整份盖掉。对话历史同理，
也在 checkpoint 里（state.messages），前端刷新后同样只能靠 GET /history 问回来。

开书（把一本书的设定从零问齐、落库）不在这个图里：那是「新建小说」弹窗专用的独立图，
见 api/novel/setup.py。这里碰到库里没有的书，只回一句让用户去弹窗建。

/run 与 /resume 走 SSE：writer / editor 的正文逐字下发，台账一个字不露（见 stream.py 的
ProseFilter）。run_novel / resume_novel 那两条非流式入口留着，测试与脚本直接调它们。
"""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.types import Command

from agents.novel import novel_agent
from agents.novel.utils.history import last_reply, visible_messages
from agents.novel.utils.inspiration import fetch_inspirations
from agents.novel.utils.run_state import (
    AWAITING,
    CANCELLED,
    DONE,
    mark_running,
    mark_settled,
    read_run,
)

from .stream import ProseFilter

router = APIRouter(prefix="/api/novel/agent", tags=["小说智能体"])

# 收尾那笔写库得单独派任务（见 _settle_later），留着强引用免得被 GC 掉跑不完。
_settle_tasks: set[asyncio.Task] = set()

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# 状态行文案：按图里的节点名报，不读任何模型输出 —— reader 的判词 JSON、summarize 的摘要
# 都不可能从这里漏出去。没列进来的节点（以及子图内 create_agent 的 model / tools）一律不报。
# writer / reader / editor 是编译子图，它们内部走到了哪一步靠一套带前缀的键报细一点：
# 键是 "父图节点.子图节点"（writer.prepare 这类），拼接见 _stage_key。
# 报的时机在 tasks 流上：任务**开跑**就报（updates 那条流要等节点跑完才来，写一章的过程里
# 状态行会一直停在"正在读取这本书的设定…"）。
_STAGE_TEXT = {
    "intension": "正在理解你的需求…",
    "load": "正在读取这本书的设定…",
    "resolve": "正在确定要写哪一章…",
    "writer": "正在写这一章…",
    "reader": "正在审稿…",
    "confirm_chapter": "等你看这一稿…",
    "editor": "正在改这一章…",
    "update": "正在落库…",
    "compact": "正在整理对话…",
    "chat": "正在回复…",
    # writer 子图：prepare → planner → write → collect
    "writer.prepare": "正在读取小说设定…",
    "writer.planner": "正在编织剧情…",
    "writer.write": "正在写这一章…",
    "writer.collect": "正在整理这一章的正文…",
    # reader 子图：gather →（logic ∥ pacing ∥ style 三路并行）→ save。
    # 三路审查并行跑，谁最后开谁的话术就盖住另外两个 —— 报不出"正在审哪一路"，
    # 索性三路共用一个"正在审稿…"，免得卡在"正在审文风…"上而其实是 pacing 在熬。
    "reader.gather": "正在准备审稿材料…",
    "reader.logic": "正在审稿…",
    "reader.pacing": "正在审稿…",
    "reader.style": "正在审稿…",
    "reader.save": "正在汇总审稿意见…",
    # editor 子图：prepare → plan → settle → impact → approve → revise → collect
    "editor.prepare": "正在准备要改的地方…",
    "editor.plan": "正在理解你要改什么…",
    "editor.settle": "正在定夺怎么改…",
    "editor.impact": "正在估算改动范围…",
    "editor.approve": "等你看这一处…",
    "editor.revise": "正在改这一章…",
    "editor.collect": "正在整理改动…",
}

# 挂了子图的父图节点：它们内部已经报过更细的那一步，父图节点跑完时别再拿粗文案盖回去。
_SUBGRAPH_NODES = frozenset({"writer", "reader", "editor"})


def _stage_key(ns, name: str) -> str:
    """tasks 流里这一条对应哪个文案键。

    父图节点就是节点名（"resolve"）；子图内部的节点拼成 "父图节点.子图节点" —— writer 与
    editor 里都有 prepare / collect，只按名字取会张冠李戴，所以带上第一段命名空间（形如
    "writer:<uuid>"）的父图节点名。
    """
    if not ns:
        return name
    owner = str(ns[0]).split(":")[0]
    return f"{owner}.{name}"


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


def _config(user_id: str, novel_id: str, chapter_id: str = "", callbacks: Optional[list] = None) -> dict:
    return {
        "callbacks": callbacks,
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


def _question(value) -> dict:
    """interrupt 交上来的问题归一化成 {text, options}。

    confirm_chapter 现在传的是对象（text 加给前端做按钮的 options）；editor.approve 那处还是
    老样子传纯字符串，这里一并兜住 —— 前端只认这一种形状。
    """
    if isinstance(value, dict):
        return {
            "text": str(value.get("text") or ""),
            "options": value.get("options") or [],
        }
    return {"text": str(value or ""), "options": []}


def _asked(result: dict) -> dict:
    """结果里那个还没答的问题；没有就空 dict。

    result 是图给的 values、或是 _final_payload 拼出来的同形字典，两种都对得上。
    """
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return {}
    first = interrupts[0] if isinstance(interrupts, (list, tuple)) else interrupts
    asked = _question(getattr(first, "value", first))
    return asked if (asked["text"] or asked["options"]) else {}


def _draft(result: dict) -> dict:
    """交上来、还没落库的那一稿正文。前端刷新后据它重建临时框。

    落库那一步会把正文从快照里抹掉（见 update），所以真有内容时一定是停在确认上。
    """
    chapter = result.get("active_chapter") or {}
    content = chapter.get("chapter_content") or ""
    if not content or chapter.get("chapter_id"):
        return {}
    return {
        "order": chapter.get("chapter_order"),
        "title": chapter.get("chapter_title") or "",
        "content": content,
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


def _history(values: dict) -> dict:
    """这本书的对话栏该有的东西：用户与助手说过的话，外加更早那批的长期摘要。

    messages 是 state 里唯一会无限长的通道，攒多了会被 compact 压进摘要、原文从里面删掉
    （见 agents/novel/utils/history.py）—— 所以这里给的就是 agent 此刻还记着的那一份，不是
    一本完整的存档。前端照它重建，用户看到的对话跟他以为 agent 记得的才是一回事。

    摘要单列一个键（不是 messages 里的一条）：它不是谁说过的话，前端要摆成一条"前情"就摆。
    """
    messages = values.get("messages") or []
    pairs = visible_messages(messages)
    return {
        "messages": [{"role": role, "content": content} for role, content in pairs],
        "summary": values.get("chat_summary") or "",
    }


def _round_reply(values: dict) -> str:
    """这一轮助手答完的那句话（用户刚问过一句、由 chat 答了才有，其余情况是空串）。

    只走 question 事件给前端补气泡：那一轮的答复进了 messages，但重摆的那一问是 interrupt，
    流里发完 question 这一轮就结束了，前端不补就只看得到问题。水合那一路不用它 —— /history
    里已经有这句话了，再补一遍就是两条。
    """
    return last_reply(values.get("messages"))


def _payload(result: dict) -> dict:
    """把图的结果折成响应体。停在 interrupt 上就把问题交回前端，否则给这一章的字段。

    停在提问上时 question 仍是那一段纯文本（脚本与测试直接读它），options / draft 是并列的
    两个附加键：前者给前端出按钮，后者是那一稿的正文。
    """
    asked = _asked(result)
    if asked:
        return {
            "interrupted": True,
            "question": asked["text"],
            "options": asked["options"],
            "draft": _draft(result),
        }

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


def _snapshot_values(snapshot) -> dict:
    """快照里的状态，外加把它各处的 interrupt 归一化回 __interrupt__ 这一个键。

    停在 interrupt 上时，这一版 langgraph 里 values 与 tasks[].interrupts 两处都可能是空的
    （实测如此），所以还要一条从 updates 流里接的来路（见 _sse），两者谁先拿到算谁。
    """
    values = dict(snapshot.values or {})
    if values.get("__interrupt__"):
        return values
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


async def _final_payload(
    user_id: str, novel_id: str, chapter_id: str, hint: Optional[dict] = None
) -> dict:
    """这一轮跑完（或停下）之后的响应体，从 checkpoint 快照取。

    hint 是 updates 流里接到的那个问题（形状同 _question）；快照没认出 interrupt 时靠它兜底。
    临时稿只在快照里，所以无论走哪条来路都从快照取。
    """
    values = _snapshot_values(await novel_agent.aget_state(_config(user_id, novel_id, chapter_id)))
    payload = _payload(values)
    if payload.get("interrupted"):
        payload["reply"] = _round_reply(values)
        return payload
    if not hint:
        return payload
    return {
        "interrupted": True,
        "question": hint.get("text") or "",
        "options": hint.get("options") or [],
        "draft": _draft(values),
        "reply": _round_reply(values),
    }


async def _pending(user_id: str, novel_id: str, chapter_id: str) -> dict:
    """这本书此刻有没有一份交了、还没确认落库的稿。

    判据跟图里那三处（reader.gather / confirm_chapter / update）同一个口径：正文非空、
    chapter_id 为空。挂得住 interrupt 的一定有正文 —— 所以拿它挡在 /run 门口就够。

    两样都得在：正文是"有这么一稿"，问题才是"这一稿正等着人答"。只认正文的话，进程中途挂掉
    留下的半截 checkpoint 也会被当成待确认，用户就永远开不了新章了 —— 认不出问题就当没停，
    退回原来的行为（照跑）。

    lastRun 是这一轮跑到哪儿的标记，几条返回路径上都给：前端据此认出"上一轮断了"（cancelled
    且手上没有待确认的稿）并提示用户重来。没有标记就是没跑过。
    """
    run = await read_run(user_id, novel_id)
    last_run = (
        {"status": run.get("status"), "intension": run.get("intension"), "at": run.get("at")}
        if run
        else None
    )

    values = _snapshot_values(await novel_agent.aget_state(_config(user_id, novel_id, chapter_id)))
    chapter = values.get("active_chapter") or {}
    if not chapter.get("chapter_content") or chapter.get("chapter_id"):
        return {"pending": False, "lastRun": last_run}
    asked = _asked(values)
    if not asked:
        return {"pending": False, "lastRun": last_run}
    return {
        "pending": True,
        "text": asked.get("text") or "",
        "options": asked.get("options") or [],
        "draft": _draft(values),
        "lastRun": last_run,
    }


def _settle_later(user_id: str, novel_id: str, status: str) -> None:
    """把收尾那笔写库派出去，不让它拖住或拖垮这一条流。

    生成器被取消（客户端断开、服务端超时）时 finally 里再 await 会立刻重抛，写不进去 ——
    那正是最需要记下"这一轮断了"的时候。所以单独派个任务，数据从参数带过去，不依赖被取消的栈。
    """
    task = asyncio.create_task(mark_settled(user_id, novel_id, status), name="novel-run-settle")
    _settle_tasks.add(task)
    task.add_done_callback(_settle_tasks.discard)


def _sse(*, user_id: str, novel_id: str, chapter_id: str, graph_input, callbacks: Optional[list] = None) -> StreamingResponse:
    """把一轮图跑成 SSE。

    事件：session / stage / target / prose_start / token / question / final / error / done。
    prose_start 表示"正文从头开始"（回炉重写也发一次，前端据此清空临时框），token 只出现在
    prose_start 之后、内容全是正文。target 是 resolve 定下的这一轮要落哪一章，在第一个 token
    之前发 —— 前端据它给在流的稿定归属，不再拿"发请求时开着的那一章"去猜。

    **必须 subgraphs=True**：writer / editor 是编译好的子图，langgraph 在 subgraphs=False 时
    直接丢掉子图里模型的 token（pregel/_messages.py 的 on_chat_model_start），正文会一个字都
    流不出来。代价是事件的形状变成三元组 (ns, mode, data)，ns 是所在的子图路径。

    三条流各司其职：messages 出正文 token，tasks 出状态行（任务开跑就报），updates 接
    interrupt（只有它接得到）与 target（只有它发得出来）。
    """
    config = _config(user_id, novel_id, chapter_id, callbacks)

    async def event_stream():
        yield _event("session", {"threadId": novel_id})
        prose = ProseFilter()
        prose_ns = ""   # 当前这条模型消息的来路，用来认出"换了一条消息"（见下面那处注释）
        question = {}   # updates 流里接到的那个问题（{text, options}），另见 _final_payload
        settled = DONE  # 这一轮到哪儿收的尾：awaiting 停在等答复，done 是正常跑完
        finished = False
        try:
            # 开跑先盖章：断开时提示"上一轮中断了"认这个标记。章号先留空 —— 请求带上来的
            # chapter_id 只是"用户开着的那一章"，它可能压根不在这一轮要动的地方（闲聊那一路
            # 连 load / resolve 都不走），拿它去挡 409 会误伤人。真正要落的那一章等 resolve
            # 定下来再盖（见下面 target 那一处），write_next 的目标章还没落库、id 为空，正是
            # "这一章谁都还没在写"该有的样子。
            await mark_running(user_id, novel_id, "")
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
                        # 每调一次模型都是新的一条消息：checkpoint_ns 末段是这一步的任务 id，
                        # 一次模型调用一个。得跟筛子说一声 —— 动笔前的寒暄单独成条，跟交稿那条
                        # 之间没有换行，粘在一个 buf 里行首的「【正文】」就认不出来了。
                        run = str((metadata or {}).get("langgraph_checkpoint_ns") or "")
                        for name, payload in prose.feed(_chunk_text(chunk), run != prose_ns):
                            yield _event(name, payload)
                        prose_ns = run
                elif mode == "tasks":
                    # 状态行在任务**开跑**时报。带 triggers 的是开始事件，带 result 的是结束。
                    # 父图节点与 writer / reader / editor 子图内部的节点都报，文案按 _stage_key 取；
                    # 子图内 create_agent 的 model / tools 不在表里，自然略过。
                    if isinstance(data, dict) and "triggers" in data:
                        key = _stage_key(ns, str(data.get("name") or ""))
                        if text := _STAGE_TEXT.get(key):
                            yield _event("stage", {"text": text})
                elif mode == "updates":
                    for node, update in (data or {}).items():
                        if node == "__interrupt__":
                            # interrupt 只从这条流里接得到（快照的 tasks[].interrupts 是空的）
                            if not question:
                                for item in update or ():
                                    asked = _question(getattr(item, "value", None))
                                    if asked["text"] or asked["options"]:
                                        question = asked
                                        break
                            continue
                        # 这一轮要落哪一章：resolve 跑完立刻发，早于 writer 的第一个 token。
                        if not ns and node == "resolve":
                            target = (update or {}).get("target")
                            if target:
                                # 章号改认真正要落的那一章：手改撞车时挡 409 就认它。write_next
                                # 若目标章还没落库（id 为空）就没人被挡 —— 那时用户在改的是别的章。
                                await mark_running(
                                    user_id,
                                    novel_id,
                                    str(target.get("chapterId") or ""),
                                    "edit" if target.get("kind") == "edit" else "write",
                                )
                                yield _event("target", target)
                        # 状态行兜底那一道：父图节点跑完再报一次同样的文案（tasks 那条流已经
                        # 在开跑时报过了，文字一模一样，前端换一遍而已）。writer / reader / editor
                        # 不报 —— 它们内部已经报过更细的那一步，这里再盖回粗文案只会倒退。
                        if (
                            not ns
                            and node not in _SUBGRAPH_NODES
                            and (text := _STAGE_TEXT.get(node))
                        ):
                            yield _event("stage", {"text": text})

            for name, payload in prose.flush():
                yield _event(name, payload)

            # 停下来的问题：流里接到的与快照里的互为备份，谁有用谁。
            final = await _final_payload(user_id, novel_id, chapter_id, question)
            if final.get("interrupted"):
                yield _event("question", {
                    "text": final.get("question") or "",
                    "options": final.get("options") or [],
                    # 这一稿还没落库：前端据它重建临时框（刷新后也照这条路恢复）。
                    "draft": final.get("draft") or {},
                    # 这一问前面还垫着一句助手的回话（用户问了一句、由 chat 答了）：前端得补成
                    # 一条气泡，否则他只见问题不见答复。水合那一路靠 /history，这里给空串。
                    "reply": final.get("reply") or "",
                })
                settled = AWAITING
            else:
                yield _event("final", final)
            yield _event("done", {})
            finished = True
        except Exception as e:  # 流已经开了，只能把错误当一条事件发出去
            yield _event("error", {"message": str(e)})
        finally:
            # 没走到 done 就是这一轮没跑完（断开 / 出错）—— 记成 cancelled，用户下次进来才知道。
            _settle_later(user_id, novel_id, settled if finished else CANCELLED)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


def _sse_pending(novel_id: str, pending: dict) -> StreamingResponse:
    """/run 被"上一稿还没确认"挡回来时，就把那件事当成一轮跑完发出去。

    形状跟正常跑一轮停在确认上一模一样（session → question → done），前端不必为这条路再写
    一套处理。
    """
    async def event_stream():
        yield _event("session", {"threadId": novel_id})
        yield _event("question", {
            "text": pending.get("text") or "",
            "options": pending.get("options") or [],
            "draft": pending.get("draft") or {},
            # 空串：这一问是上一轮留下的，那轮的回话早随它自己那条 question 事件推过气泡了，
            # 这里再推一遍就是两条（水合那一路同理，回话在 /history 里）。
            "reply": "",
        })
        yield _event("done", {})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/run")
async def call_novel_agent(
    request: Request,
    novelId: str = Form(...),
    text: str = Form(...),
    chapterId: Optional[str] = Form(None),
    inspirationIds: str = Form("[]"),
):
    """把一句话交给小说图，流式跑这一轮；停在提问上就把问题交给前端。

    开书不走这里（那是弹窗专用的 api/novel/setup.py）：库里没有这本书时，load 会回一句
    引导用户去弹窗建。

    上一稿还停在确认上就别往下跑：writer 一 save 就用整份 active_chapter 盖掉正文，拦在图里
    已经晚了（拦在 intension 也一样晚）。所以守在这儿，把那个问题原样发回去。

    用户这一轮挑中的灵感（inspirationIds，灵感库内已有行的 id）在过了这道门禁之后按 id 取回，
    随 state.inspirations 进图：**只取不落库** —— 灵感在灵感库新增时就入了库，对话这里只是
    点名要用哪几条。取回的行带真 id，落章后 update 据此补 usedChapterIds。
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="至少说一句要写什么")

    user_id = str(request.state.user_id)
    chapter_id = chapterId or ""
    pending = await _pending(user_id, novelId, chapter_id)
    if pending.get("pending"):
        return _sse_pending(novelId, pending)

    try:
        ids = json.loads(inspirationIds or "[]")
    except ValueError:
        ids = []
    if not isinstance(ids, list):
        ids = []
    selected = await fetch_inspirations(novelId, [str(i) for i in ids if i])

    handler = getattr(request.state, "token_collector", None)
    return _sse(
        user_id=user_id,
        novel_id=novelId,
        chapter_id=chapter_id,
        graph_input={
            "user_id": user_id,
            "user_message": text,
            "inspirations": selected,
        },
        callbacks=[handler] if handler else None,
    )


@router.get("/pending")
async def pending_novel_agent(
    request: Request,
    novelId: str = Query(...),
    chapterId: Optional[str] = Query(None),
):
    """这本书此刻有没有一份交了、还没确认落库的稿。

    前端刷新 / 切书时拿它重建现场：问题、按钮、临时框三样都在返回里（pending 为假时只有
    这一个键）。/resume 是这个问题的正经去路，别拿这道守卫去挡它。
    """
    return await _pending(str(request.state.user_id), novelId, chapterId or "")


@router.get("/history")
async def history_novel_agent(request: Request, novelId: str = Query(...)):
    """这本书的对话历史：前端进页面 / 切回这本书时拿它把对话栏重建回来。

    对话只存在于 checkpoint 里（前端手上那份是内存里的，刷新就没了），所以恢复只能问这儿。
    一个 thread 就是一本小说，所以只有 novelId 一个参数 —— 对话整本一条，切章不换会话。
    """
    values = _snapshot_values(
        await novel_agent.aget_state(_config(str(request.state.user_id), novelId))
    )
    return _history(values)


@router.post("/clear")
async def clear_novel_agent(request: Request, novelId: str = Form(...)):
    """清空这本书的对话记忆（用户点了"清空对话"）。

    对话只活在 checkpoint 里，光清前端那几条气泡是假的 —— 一刷新又原样回来。这里把 messages
    与长期摘要一起清掉：agent 从此不记得之前聊过什么，用户看到的也就是空的。库里的章节与
    设定一个字不动（对话本来就不在库里）。

    正停在提问上（有一稿等着确认）时不给清：改状态会把这轮的 interrupt 从快照上抹掉 ——
    /pending 认不出它、/run 那道门禁也就不挡了，那份还没落库的正文再没人看得见（resume 本身
    还接着跑，等于把用户悬在半空）。所以先让他把那一稿收下或改完再清。
    """
    config = _config(str(request.state.user_id), novelId)
    if _snapshot_values(await novel_agent.aget_state(config)).get("__interrupt__"):
        raise HTTPException(
            status_code=409, detail="有一稿还没确认落库，先把它收下或改完再清空对话。"
        )

    await novel_agent.aupdate_state(
        config,
        {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)], "chat_summary": ""},
    )
    return {"cleared": True}


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
