"""reader 审完 → 无论通过与否都停下来问用户，收下才落库。write / edit 共用这一问。

取代原来的 ask_fix：那时只有 edit 这条路会停下来（新章是静默回炉，回炉次数用完静默收下）。
回炉目标按 intension 分，两条路的回炉机制各自是现成的：
  write → writer，_briefing 见 chapter_review 的 problems 或 edit_feedback 就走 _retry_note
  edit  → editor，_is_redo 见这两样就走 _redo_plan
判断"要不要改"复用 utils.verdict 与 KEEP_PROMPT（它判的就是收下 / 要改 / 含糊）。
"""
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt

from ..state import State
from ..utils.model import intentModel
from ..utils.prompt import KEEP_PROMPT
from ..utils.verdict import verdict


async def confirm_chapter(state: State, config: RunnableConfig) -> Command:
    """interrupt 之前只读 state：节点恢复时会从头重跑，写在它前面的副作用会走两遍。"""
    chapter = state.get("active_chapter") or {}
    # 这一轮没有新稿（editor 空跑、load 发现书还没建、闲聊）：没什么可确认的，直接去收尾。
    # 与 reader.gather、update 同一个口径 —— chapter_id 非空就是"不是本轮交的稿"。
    if not chapter.get("chapter_content") or chapter.get("chapter_id"):
        return Command(goto="update")

    review = state.get("chapter_review") or {}
    order = chapter.get("chapter_order")
    attempt = state.get("chapter_attempt", 0)
    passed = review.get("passed", True)
    problems = (review.get("problems") or "").strip() or "审查这一关没过，但没写出具体问题。"

    if passed:
        question = (
            f"第 {order} 章写完了（第 {attempt} 稿），审查这一关过了。\n\n"
            "收下它、我这就存进这一章？要再改改的话，直接说往哪儿改。"
        )
    else:
        question = (
            f"第 {order} 章写完了（第 {attempt} 稿），但审查这一关没过：\n\n{problems}\n\n"
            "要我按这些意见改一版，还是就这样收下？要改的话说一句往哪儿改。"
        )

    answer = interrupt(question)

    reply = await intentModel.ainvoke(
        [SystemMessage(content=KEEP_PROMPT), HumanMessage(content=str(answer or ""))]
    )
    text = reply.content if isinstance(reply.content, str) else ""
    keep, feedback = verdict(text, "keep")

    if keep:
        # review 一并改成"通过"再走：后面落库只认这一稿成没成，旧问题不带进去。
        # 状态留在 draft：收下只是"这稿存进这一章"，定不定稿由用户在前端自己标（完成 / 待修复）。
        # active_chapter 在父图是整份覆盖，交回去的必须是全量，漏了键就等于抹掉。
        return Command(
            goto="update",
            update={
                "active_chapter": {**chapter, "chapter_status": "draft"},
                "chapter_review": {"passed": True, "problems": ""},
                "edit_feedback": "",
            },
        )

    # 答复含糊（feedback 为空）时：这稿本来就过了就不再折腾，按收下办；没过则按要改办 ——
    # 宁可多改一版，也不把一处已经审出来的问题就这样收下。
    if passed and not feedback:
        return Command(
            goto="update",
            update={
                "active_chapter": {**chapter, "chapter_status": "draft"},
                "chapter_review": {"passed": True, "problems": ""},
            },
        )

    # chapter_review 原样留着：write 回炉靠 problems、edit 回炉靠 _is_redo（problems 或 feedback）。
    target = "writer" if state.get("intension") == "write" else "editor"
    return Command(goto=target, update={"edit_feedback": feedback or str(answer or "")})
