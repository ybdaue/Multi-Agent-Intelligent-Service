"""manual 节点（人工改稿）：比对 原稿 vs 用户改后的稿，重报这一章的台账并定严重程度。

用户自己在正文框里改完点保存，改后正文随请求带上来（state.manual_content）。这一节点不写正文
（用户已经改好了），只拿主模型读一遍两稿的差异：报出这一章改完用到 / 新造 / 真改了值的设定，
并给这次改动定 L1/L2/L3。之后交回父图，由 route_after_draft 按 grade 决定 reader 走哪几路。
"""
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from agents.utils.models import ainvoke_with_fallback

from ...utils.chapter_information import count_chapter_words, get_chapter
from ...utils.ledger import (
    auto_complete_refs,
    fetch_catalog,
    fetch_chapter_refs_by_id,
    fetch_names,
    parse_grade,
    parse_ledger,
)
from ...utils.prompt import MANUAL_EDIT_PROMPT
from .helpers import _manual_backup, _manual_brief, _manual_main
from .state import EditorState

# 能改的状态：草稿 / 待修复。已定稿（done）与生成中都不许 —— 与前端保存按钮置灰同一口径，
# 这是后端的第二道闸（前端能置灰，但接口不能只靠前端自觉）。
_EDITABLE_STATUSES = frozenset({"draft", "fixing"})

_ROLE_LABEL = {"key": "关键", "state": "交代", "mention": "提及"}


def _refs_text(refs: list[dict]) -> str:
    """上一版台账排成给人看的几行（模型照它认"这一章原来挂了哪些"）。"""
    return "\n".join(
        f"- {ref['refType']} {ref['refId']}（{_ROLE_LABEL.get(ref.get('role') or '', '提及')}）"
        for ref in refs
    )


async def manual(state: EditorState, config: RunnableConfig) -> dict:
    """人工改稿：读原稿与改后稿，重报台账 + 定严重程度，收入 active_chapter 交回父图。"""
    novel_id = (config.get("configurable") or {}).get("novel_id")
    order = (state.get("target_chapter") or {}).get("chapter_order")
    if not novel_id or not order:
        return {"plan": {}, "edit_note": "没认出要改的是哪一章，改不了。"}

    row = await get_chapter(novel_id, order)
    if row is None:
        return {"plan": {}, "edit_note": f"库里没有第 {order} 章，改不了。"}
    if str(row.get("chapter_status") or "draft") not in _EDITABLE_STATUSES:
        return {"plan": {}, "edit_note": "已定稿的章节不能改，先把它改回草稿或待修复。"}

    modified = (state.get("manual_content") or "").strip()
    if not modified:
        return {"plan": {}, "edit_note": "没收到改后的正文，改不了。"}

    # 上一版台账（本章自己的，不是上一章的）+ 设定目录：供模型认 id、判哪几条不再用到。
    refs_text = _refs_text(await fetch_chapter_refs_by_id(row["chapter_id"]))
    catalog = await fetch_catalog(novel_id)
    reply = await ainvoke_with_fallback(_manual_main, _manual_backup, [
        SystemMessage(content=MANUAL_EDIT_PROMPT),
        HumanMessage(content=_manual_brief(state, row.get("chapter_content") or "", refs_text, catalog)),
    ])
    text = reply.content if isinstance(reply.content, str) else ""

    refs, new_entries, changed_entries, _, _ = parse_ledger(text)
    grade = parse_grade(text)
    # 给了 refs 才补扫漏报的已有实体；没给（None）就不动旧的关联（语义同 writer / editor.collect）。
    if refs is not None:
        refs = auto_complete_refs(refs, modified, await fetch_names(novel_id))

    return {
        "active_chapter": {
            "chapter_id": "",                       # 空 = 本轮新交的这一稿，还没落库
            "chapter_title": row.get("chapter_title") or "未命名",
            "chapter_order": order,
            "chapter_status": row.get("chapter_status") or "draft",
            "chapter_word_count": count_chapter_words(modified),
            "chapter_summary": row.get("chapter_summary") or "",  # summarize 节点按新正文刷新
            "chapter_content": modified,
            "past_summary": row.get("past_summary") or {},
            "chapter_state": {},
            "chapter_inspirations": [],
            "chapter_refs": refs,
            "chapter_new": new_entries,
            "chapter_changed": changed_entries,
            # 人工改正文不碰阶段线 / 支线 / 大纲 ref（留空 / None = 落库时那一块一行不动）。
            "chapter_lines": [],
            "chapter_outline_refs": None,
        },
        "change_grade": grade,
        # 消费掉 manual_content：别让它跨轮残留、把下一轮误判成人工改。
        "manual": False,
        "manual_content": "",
        "setting_changes": [],
        "change_impact": [],
        "edit_note": "",
    }