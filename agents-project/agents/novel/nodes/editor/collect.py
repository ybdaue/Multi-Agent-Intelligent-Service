"""collect 节点：收这一稿 —— 切正文与台账，其余字段沿用库里那一行，序号照旧（不新起一章）。"""
from langchain_core.runnables import RunnableConfig

from ...utils.chapter_information import count_chapter_words, split_title
from ...utils.ledger import (
    auto_complete_refs,
    fetch_names,
    parse_grade,
    parse_ledger,
    split_submission,
)
from ..utils.reply import last_reply
from .state import EditorState


async def collect(state: EditorState, config: RunnableConfig) -> dict:
    """收这一稿：切正文与台账，其余字段沿用库里那一行，序号照旧（不新起一章）。"""
    row = state.get("target") or {}
    order = row.get("chapter_order")
    content = last_reply(state.get("messages"))
    prose, ledger_text = split_submission(content)
    if not prose or not order:
        # 改稿没交上来，这次改动就没发生：影响台账一并撤掉，别让 update 当成"改过了"记进库。
        return {
            "plan": {},
            "setting_changes": [],
            "change_impact": [],
            "edit_note": "这一版没改出来（回复是空的），你再说一次要改哪里。",
        }

    # 标题行摘出来单独放（原稿的正文里本来也没有它），改稿没写标题就用原来那条。
    prose, title = split_title(prose)

    # refs 可能是 None（没给台账）：落库时旧的关联一行不动，留着上一稿的。
    # 改稿不报阶段线 / 支线（那是写手往下写时的事），也不收尾伏笔 —— 后三项丢掉。
    refs, new_entries, changed_entries, _, _ = parse_ledger(ledger_text)
    grade = parse_grade(ledger_text)

    # 改章给了台账才补扫漏报的已有实体；没给就不动旧的关联（None 语义不变）。
    if refs is not None:
        novel_id = (config.get("configurable") or {}).get("novel_id")
        if novel_id:
            known_rows = await fetch_names(novel_id)
            refs = auto_complete_refs(refs, prose, known_rows)
    return {
        "active_chapter": {
            "chapter_id": "",
            "chapter_title": title or row.get("chapter_title") or "未命名",
            "chapter_order": order,
            "chapter_status": row.get("chapter_status") or "draft",
            "chapter_word_count": count_chapter_words(prose),
            "chapter_summary": row.get("chapter_summary") or "",  # summarize 节点按新正文刷新
            "chapter_content": prose,
            "past_summary": row.get("past_summary") or {},        # 同上
            "chapter_state": {},
            "chapter_inspirations": [],
            "chapter_refs": refs,
            "chapter_new": new_entries,
            # 这一稿真改了值的已有设定（会变值那五类）：update 照旧行建一版新行（见 ledger 版本链）。
            "chapter_changed": changed_entries,
            # 改稿不碰阶段线 / 支线：留空 = 落库时一行大纲都不动（见 ledger.write_lines）。
            "chapter_lines": [],
            # 也不动大纲 ref（None = 保留上一稿的 outline 关联，见 ledger.write_outline_refs）。
            "chapter_outline_refs": None,
        },
        # 这一稿的严重程度（随台账报的 L1/L2/L3）：父图 route_after_draft 据它决定 reader 走哪几路。
        "change_grade": grade,
    }