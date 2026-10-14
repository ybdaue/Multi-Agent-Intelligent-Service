"""落库：把这一轮定下的东西写进库（章节、设定改动、影响台账），清掉本轮记号，最后回用户一句话。

三笔都集中在这里写（子图只管把结果摆好）。设定改动与影响台账必须放在章节那道守卫前面：
只改设定的一轮没有新章，但它照样得落库。
靠 chapter_id 空不空认这一轮有没有新交的稿（active_chapter 是跨轮留着的，只看正文会把上一轮
那一章反复重写）；update 是这一轮的终点，顺手把回炉记号清掉。
"""
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from ..state import State
from ..utils.chapter_information import count_chapter_words, upsert_chapter
from .utils.impact import write_edits
from ..utils.inspiration import mark_used


async def update(state: State, config: RunnableConfig) -> dict:
    """落库这一轮定下的东西，回填章节 id，再把本轮记号清掉。"""
    # 收尾时一律带上：闲聊、没改成的稿这些不写章节的路也要把记号清干净。
    fresh = {
        "chapter_review": {},
        "chapter_conflicts": [],
        "chapter_attempt": 0,
        "edit_feedback": "",
        "edit_note": "",
        "setting_changes": [],
        "change_impact": [],
        "target_chapter": {},
        # 灵感只在灵感库那边入库，这里只清本轮记号；哪几章用了哪几条由下面 mark_used 补。
        "inspirations": [],
        "chapter_inspirations": [],
    }
    # 回话攒成一条：前端只拿最后一条助手消息。
    lines = []

    note = (state.get("edit_note") or "").strip()
    if note:
        lines.append(note)

    novel_id = (config.get("configurable") or {}).get("novel_id")
    setting_changes = state.get("setting_changes") or []
    impact = state.get("change_impact") or []

    # 这一笔先写：只改设定那一轮没有新章，走不到下面的章节守卫里。
    if novel_id and (setting_changes or impact):
        written = await write_edits(novel_id, setting_changes, impact)
        if setting_changes:
            created = any(change.get("mode") == "create" for change in setting_changes)
            lines.append("库里新增了一条设定。" if created else "设定改好了。")
        if written:
            lines.append(f"这次改动顺带记下 {written} 处可能受影响的地方，在改动清单里可以逐条看。")

    chapter = state.get("active_chapter") or {}
    if (
        novel_id
        and chapter.get("chapter_content")
        and chapter.get("chapter_order") is not None
        and not chapter.get("chapter_id")
    ):
        chapter = dict(chapter)
        # 字数重算一遍再落，不采信交稿时的那个数。
        chapter["chapter_word_count"] = count_chapter_words(chapter["chapter_content"])
        chapter_id, _ = await upsert_chapter(novel_id, chapter)

        # 这一章用到的灵感：写新章用 planner 定下的 chapter_inspirations（含必用 / 风格 / 用户点名）；
        # 改章 / editor 那一路没有它，退回本轮用户点名的 inspirations。记进那几条的 usedChapterIds。
        used = state.get("chapter_inspirations") or state.get("inspirations") or []
        await mark_used([item["id"] for item in used if item.get("id")], chapter_id)

        # 改既有章节和写新章用词不一样：用户这一轮要的是"改"，回他"已写好"像答错了。
        verb = "已改好" if state.get("intension") == "edit" else "已写好"
        lines.append(
            f"第 {chapter['chapter_order']} 章《{chapter.get('chapter_title') or '未命名'}》"
            f"{verb}，{chapter['chapter_word_count']} 字。"
        )

        # 整份交回，不能只给 chapter_id：active_chapter 没有 reducer，给什么就是什么。
        # 正文落库之后就从 state 里抹掉：整章几千字，留着就是每一份快照都复制一份，而它
        # 只在"本轮这一稿"里有意义 —— 下一轮真要改这一章，editor 会按序号重新查库。
        return {
            **fresh,
            "active_chapter": {**chapter, "chapter_id": chapter_id, "chapter_content": ""},
            "messages": [AIMessage(content="\n\n".join(lines))],
        }

    if lines:
        return {**fresh, "messages": [AIMessage(content="\n\n".join(lines))]}
    return fresh
