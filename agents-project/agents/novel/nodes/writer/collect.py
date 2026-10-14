"""collect 节点（查库，不调模型）：切正文与台账、定标题字数、算序号，收入 active_chapter。"""
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from langgraph.types import Command

from ...utils.chapter_information import (
    count_chapter_words,
    next_chapter_order,
    split_title,
)
from ...utils.ledger import (
    auto_complete_refs,
    fetch_names,
    parse_ledger,
    split_submission,
)
from ..utils.reply import last_reply
from .helpers import _card_lines
from .state import WriterState


async def collect(state: WriterState, config: RunnableConfig) -> Command:
    """收稿：切正文与台账、定标题字数、算序号，阶段线/支线照 planner 的任务卡落。

    字数合格与否**不在这里回炉**：交回父图后由 reader 那一路去判（它在审稿时一并数字数），
    真正的回炉由用户在 confirm_chapter 那儿拍板。这儿只管把这一稿收成 active_chapter。
    """
    content = last_reply(state.get("messages"))
    novel_id = (config.get("configurable") or {}).get("novel_id")
    if not content or not novel_id:
        # 写手什么都没交（或拿不到书号）：这一轮到此为止，不硬造一份空章节。
        return Command(goto=END)

    # 先切台账再数字数：台账是元信息不是正文，混在一起会算进字数、也会被存进正文。
    # 标题行也在这儿摘走（存 chapter_title），正文里不留它 —— 数的是正文，摘不摘都一样。
    prose, ledger_text = split_submission(content)
    prose, title = split_title(prose)
    words = count_chapter_words(prose)

    # 台账两项：用到 / 提示的已有设定、新造的实体。lines 由 planner 的任务卡定，写手不再报。
    # 父链（阶段线挂主线、支线挂阶段线）要照本章的 writer_context 解，所以把上下文一并传进去。
    refs, new_entries, _ = parse_ledger(ledger_text)
    known_rows = await fetch_names(novel_id)
    refs = auto_complete_refs(refs, prose, known_rows)
    lines = _card_lines(state.get("task_card") or {}, state.get("writer_context") or {})

    # 序号以库里的为准（最大序号 + 1），不接受调用方指定。
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
                "chapter_lines": lines,
            }
        },
    )