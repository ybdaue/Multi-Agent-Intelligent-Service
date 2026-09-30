"""写新章：agent 照 writerSkill 写出正文，节点收下，交回父图。

prepare 备料（复用父图缓存的 writer_context）、write 写、save 收稿并卡字数。
收稿与回炉全在图里，模型忘写台账最多少条关联记录。子图对话不上交父图。"""

import json
from typing import Annotated, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command

from ..state import ChapterMeta, ChapterReview, NovelMeta, merge_chapter
from ..tools import fetchDB, read_skill_file
from ..utils.chapter_information import (
    CHAPTER_MAX_WORDS,
    CHAPTER_MIN_WORDS,
    MAX_WRITE_TRIES,
    count_chapter_words,
    get_writer_context,
    next_chapter_order,
    split_title,
)
from ..utils.inspiration import render_inspirations
from ..utils.ledger import parse_ledger, split_submission, auto_complete_refs, fetch_names
from ..utils.model import MainModel
from ..utils.novel_information import render_protagonists
from ..utils.prompt import WRITER_PROMPT
from ..utils.trace import traced


class WriterInput(TypedDict):
    novel: NovelMeta
    active_chapter: ChapterMeta
    chapter_review: ChapterReview
    chapter_attempt: int
    edit_feedback: str
    user_message: str
    inspirations: list
    writer_context: dict                # resolve 预查的上下文，prepare 复用跳过查库


class WriterOutput(TypedDict):
    """交回父图的：这一章，和回炉计数。子图自己的对话与内部计数不上交。"""

    active_chapter: ChapterMeta
    chapter_review: ChapterReview
    chapter_attempt: int


class WriterState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    novel: NovelMeta
    active_chapter: Annotated[ChapterMeta, merge_chapter]
    chapter_review: ChapterReview
    chapter_attempt: int
    edit_feedback: str
    user_message: str
    inspirations: list
    write_tries: int
    writer_context: dict                # resolve 预查的上下文，prepare 复用


# 不挂 run_skill_script（不建文件、不跑脚本，字数在 save 里用 Python 卡）、
# 不挂任何"交稿"工具（正文与台账就是模型的回复，切开与落库是 save / update 的事）。
# 开着流式：这一路的 token 要逐字发给前端当打字机。台账由 api/novel/stream.py 的
# ProseFilter 在【本章台账】处截掉，落库仍走 save 的 split_submission，两边同一个标记。
try:
    _writer_main = MainModel(temperature=0.7, disable_streaming=False)
except Exception:
    _writer_main = None

_writer_agent = create_agent(
    model=_writer_main,
    tools=[read_skill_file, fetchDB],
    system_prompt=WRITER_PROMPT,
    state_schema=WriterState,
)


def _retry_note(state: WriterState, order: int, problems: str, feedback: str = "") -> str:
    """上一稿被打回时的抬头：原稿全文 + 审查意见 / 用户要求，让模型在原稿上改。"""
    chapter = state.get("active_chapter") or {}
    lines = [f"【回炉重写】第 {order} 章的上一稿要再改一版。"]
    if problems:
        lines.append(f"审查意见：\n\n{problems}")
    # 审查通过、用户却要再改时 problems 是空的，只有这一块 —— 少了它模型就无从改起。
    if feedback:
        lines.append(f"用户看过这一稿之后又说：\n\n{feedback}")

    draft = (chapter.get("chapter_content") or "").strip()
    if draft:
        lines.append(
            "上一稿全文如下。按上面的意见改那几处，其余内容保留，不要整章从头重写，"
            f"也不要借机改设定：\n\n{draft}"
        )
    lines.append(
        f"改完还是第 {order} 章，整章重发一次；字数仍要 {CHAPTER_MIN_WORDS}-{CHAPTER_MAX_WORDS}。"
        f"开头照旧独占一行写「【正文】」，末尾的台账照这份重发一遍"
        f"（改完用了什么、新造了什么，可能跟上一稿不一样了）。"
    )
    return "\n\n".join(lines)


def _briefing(state: WriterState, context: dict) -> str:
    """交给 agent 的开场：这一章是第几章，备齐的材料一次给全。"""
    novel = state.get("novel") or {}
    order = context["chapter_order"]
    review = state.get("chapter_review") or {}
    problems = "" if review.get("passed", True) else (review.get("problems") or "").strip()
    feedback = (state.get("edit_feedback") or "").strip()

    lines = [f"请写第 {order} 章。" + ("（回炉重写）" if (problems or feedback) else "")]
    if problems or feedback:
        lines.append(_retry_note(state, order, problems, feedback))
    # 用户这一轮自己说的那句要原样摆进来：「这一章只写什么、不写什么」只说在这句话里。
    # 回炉时也照摆，但说法得换：回炉意味着读者看过这一稿之后点了"按库里改"（或审查没过），
    # 那是他后来改的口 —— 再让"以他原话为准"压在上面，两边就一直对着干、来回空转。
    said = (state.get("user_message") or "").strip()
    if said:
        if problems or feedback:
            lines.append(f"用户当初对这一章的要求（按上面的回炉意见来，别照它顶）：\n\n{said}")
        else:
            lines.append(f"用户对这一章的要求（照它写，它跟大纲冲突时以它为准）：\n\n{said}")
    inspirations = render_inspirations(state.get("inspirations") or [])
    if inspirations:
        lines.append(f"用户这次给的素材：\n{inspirations}")

    lines.append(
        f"《{novel.get('novel_title') or '未命名'}》；"
        f"小说套路：{novel.get('novel_tropes') or '未填'}；"
        f"小说风格：{novel.get('novel_style') or '未填'}。"
    )

    protagonists = render_protagonists(novel)
    if protagonists:
        lines.append(f"主角：\n{protagonists}")

    outlines = [text for text in (context.get("outlines") or []) if text.strip()]
    if outlines:
        lines.append("本章生效的大纲：\n\n" + "\n\n".join(outlines))
    else:
        lines.append("库里还没有本章适用的大纲，就按前文和你对这本书的了解往下写。")

    world_rules = context.get("world_rules") or []
    if world_rules:
        rules = "\n".join(f"- {r['name']}：{r['rule']}" for r in world_rules)
        lines.append(f"本章生效的世界规则、力量体系，别写崩：\n{rules}")
    else:
        lines.append("库里还没有本章适用的世界规则。")

    prev_content = (context.get("prev_content") or "").strip()
    if prev_content:
        lines.append(f"上一章（第 {order - 1} 章）全文，接着它写：\n\n{prev_content}")
    else:
        lines.append("这是本书第一章，没有上一章可接，自己开篇。")

    prev_prev_summary = (context.get("prev_prev_summary") or "").strip()
    if prev_prev_summary:
        lines.append(f"上上一章（第 {order - 2} 章）的精简：\n\n{prev_prev_summary}")

    past_summary = context.get("prev_past_summary") or {}
    past_text = (past_summary.get("text") or "").strip() if isinstance(past_summary, dict) else ""
    if past_text:
        lines.append(f"到第 {order - 1} 章为止的前文总结：\n\n{past_text}")

    catalog = (context.get("catalog") or "").strip()
    if catalog:
        lines.append(
            "库里已有的设定目录（每行是「id 名字」，id 是后面台账要用的编号）：\n\n"
            f"{catalog}\n\n"
            "这一章用到或提到目录里的哪一条，就在台账的 refs 里报它的 id；"
            "这一章新造的人物、势力、物品，在 new 里报名字。要看某一条的细节（目录只给了名字，"
            "大纲、伏笔这些还截了字），用 fetchDB 按名字点查那一条，别整表拉。"
        )
    else:
        lines.append(
            "库里还没有任何设定，目录是空的。这一章用到的都是新造的，照「交稿」一节报进 new。"
        )
    return "\n\n".join(lines)


async def prepare(state: WriterState, config: RunnableConfig) -> dict:
    """取这一章要用的材料，复用 resolve 缓存的 writer_context，跳过重复查库。"""
    handed = {
        "chapter_attempt": state.get("chapter_attempt", 0) + 1,
        "chapter_review": {"passed": True, "problems": ""},
        "write_tries": 0,
    }
    novel_id = (config.get("configurable") or {}).get("novel_id")
    if not novel_id:
        return {
            **handed,
            "messages": [HumanMessage(content="拿不到当前这本书的编号，写不了。")],
        }

    context = state.get("writer_context") or await get_writer_context(novel_id)
    return {
        **handed,
        "messages": [HumanMessage(content=_briefing(state, context))],
    }


def _last_reply(messages) -> str:
    """最后一条没有工具调用的助手回复 —— 写手的交稿就是它。"""
    for message in reversed(messages or []):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            content = message.content
            if isinstance(content, str) and content.strip():
                return content
    return ""


def _word_hint(words: int) -> str:
    """字数不合格时打回去，让它整章重发。"""
    if words < CHAPTER_MIN_WORDS:
        return (
            f"刚这一稿才 {words} 字，不够 {CHAPTER_MIN_WORDS}。照 references/content-expansion.md "
            f"把情节写开、把场景和对话补足，还是这一章、不要另起一章，改完整章重发一次"
            f"（开头照旧写「【正文】」，末尾的台账照旧，别省）。"
        )
    return (
        f"刚这一稿 {words} 字，超了 {CHAPTER_MAX_WORDS}。番茄单章太长会掉完读率，"
        f"精简到 {CHAPTER_MIN_WORDS}-{CHAPTER_MAX_WORDS} 之间再整章重发一次"
        f"（开头照旧写「【正文】」，末尾的台账照旧，别省）。"
    )


async def save(state: WriterState, config: RunnableConfig) -> Command:
    """收稿：正文与台账在这儿切开，标题、字数在这儿定，序号由库里现算，不合格就回到 write 重写。"""
    content = _last_reply(state.get("messages"))
    novel_id = (config.get("configurable") or {}).get("novel_id")
    if not content or not novel_id:
        # 写手什么都没交（或拿不到书号）：这一轮到此为止，不硬造一份空章节。
        return Command(goto=END)

    # 先切台账再数字数：台账是元信息不是正文，混在一起会算进字数、也会被存进正文。
    # 标题行也在这儿摘走（存 chapter_title），正文里不留它 —— 数的是正文，摘不摘都一样。
    prose, ledger_text = split_submission(content)
    prose, title = split_title(prose)
    words = count_chapter_words(prose)

    # 台账放在字数之前解析：字数回炉时要带上当前 refs/new 作提示，不能依赖它俩在后面的定义。
    refs, new_entries = parse_ledger(ledger_text)
    known_rows = await fetch_names(novel_id)
    refs = auto_complete_refs(refs, prose, known_rows)

    tries = state.get("write_tries", 0)
    if not CHAPTER_MIN_WORDS <= words <= CHAPTER_MAX_WORDS and tries + 1 < MAX_WRITE_TRIES:
        hint = _word_hint(words)
        if refs or new_entries:
            hint += "\n\n上一稿的台账（改完把这几条也报上，少了的再补）："
            if refs:
                hint += f"\nrefs: {json.dumps(refs, ensure_ascii=False)}"
            if new_entries:
                hint += f"\nnew: {json.dumps(new_entries, ensure_ascii=False)}"
        return Command(
            goto="write",
            update={"write_tries": tries + 1, "messages": [HumanMessage(content=hint)]},
        )

    # 序号以库里的为准；字数回炉次数用完时不合格的稿子也照收，留给 reader 那一路去判。
    chapter_order = await next_chapter_order(novel_id)
    return Command(
        goto=END,
        update={
            "active_chapter": {
                "chapter_id": "",
                "chapter_title": title or "未命名",
                "chapter_order": chapter_order,
                "chapter_status": "draft",
                "chapter_word_count": words,
                "chapter_summary": "",
                "chapter_content": prose,
                "past_summary": {},
                "chapter_state": {},
                "chapter_inspirations": [],
                "chapter_refs": refs,
                "chapter_new": new_entries,
            }
        },
    )


# 进出一行人话打印（agents/novel/utils/trace.py），只管调式，不动流程。
# write 那一步是 create_agent 子图，没有能挂打印的节点函数 —— 它的起止看前后两个节点。
_writer_flow = StateGraph(WriterState, input_schema=WriterInput, output_schema=WriterOutput)
_writer_flow.add_node("prepare", traced("writer.prepare")(prepare))
_writer_flow.add_node("write", _writer_agent)
_writer_flow.add_node("save", traced("writer.save")(save))
_writer_flow.add_edge(START, "prepare")
_writer_flow.add_edge("prepare", "write")
_writer_flow.add_edge("write", "save")
# save 自己决定回炉还是收工（Command 的 goto），两条路都在图里，不由模型挑。
_writer_flow.add_edge("save", END)

# 不带 checkpointer：挂进父图时就用父图那个，子图每一步都落在同一个 thread 上。
writer = _writer_flow.compile(name="novel_writer")
