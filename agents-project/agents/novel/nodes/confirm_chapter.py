"""reader 审完 → 无论通过与否都停下来问用户，收下才落库。write / edit 共用这一问。

取代原来的 ask_fix：那时只有 edit 这条路会停下来（新章是静默回炉，回炉次数用完静默收下）。
回炉目标按 intension 分，两条路的回炉机制各自是现成的：
  write → writer，_briefing 见 chapter_review 的 problems 或 edit_feedback 就走 _retry_note
  edit  → editor，_is_redo 见这两样就走 _redo_plan
判断"要不要改"复用 utils.verdict 与 KEEP_PROMPT（它判的就是收下 / 要改 / 没表态）。

**只有点按钮、或明说要收下，才算确认**。用户没点按钮、而是问了一句（"这里为什么这么写"）
时，那一句算没表态：先转给 chat 把话答了（chat 之后认得出这一稿还没落库，转回这里再问一次），
正文一直留在 active_chapter 里 —— 从前"没表态就当收下"的老口径会让一次普通的提问把稿子
静默落库（他没确认，库里的正文却已经换成了这一稿）。

用户这一轮的要求跟库里对不上的那几处（reader 的 chapter_conflicts）也并进这一问一起定夺：
他说保留就照他的写，那几处偏离记成影响台账（落库在 update）；说按库里改就回炉。前端把这两个
出口做成按钮，答复是 {"option": "keep" / "revise"}，认得出就不必再过模型。
"""
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt

from agents.utils.models import parse_json_value
from ..state import ChapterConflict, State
from ..utils.model import intentModel
from ..utils.prompt import KEEP_PROMPT
from ..utils.verdict import verdict

# 用户选了保留时，那几行影响台账的 resolution 写什么（前端显示成"处理：…"）。
_RESOLUTION = "你确认保留这一处偏离"


def _conflict_lines(conflicts: list[ChapterConflict]) -> str:
    """把偏离摆成人话，一处一行 —— 用户要就着这几行决定留还是改。"""
    return "\n".join(
        f"- 库里《{c['targetName'] or '未命名'}》记的是：{c['rule'] or '（没写清）'}；"
        f"你要的是：{c['want'] or '（没写清）'}"
    )


def _choice(answer) -> str:
    """前端按钮回传的那个选项。用户自己打字答的（不是按钮）交空串，由 KEEP_PROMPT 去判。"""
    try:
        value = parse_json_value(str(answer or ""))
    except ValueError:
        return ""
    if isinstance(value, dict) and value.get("option") in ("keep", "revise"):
        return str(value["option"])
    return ""


def _redo_feedback(conflicts: list[ChapterConflict], problems: str) -> str:
    """点了"按库里改"时交给回炉那一路的话（write 并进 _retry_note，edit 并进 _redo_plan）。

    按钮回答没有"用户原话"可用，得把要改的地方替他说清楚，否则模型不知道改什么。
    """
    lines = []
    if problems:
        lines.append(f"审查这一关没过，这几处要改：\n{problems}")
    if conflicts:
        lines.append(
            "库里这几处的口径照旧的来，别保留我这次要的写法：\n"
            + _conflict_lines(conflicts)
        )
    return "\n\n".join(lines)


def _impact_rows(conflicts: list[ChapterConflict], order) -> list[dict]:
    """用户选了保留：每一处偏离记一行影响台账，由 update 落库。

    一处一个 changeId（不是一次确认共用一个）：这几行的 targetId 是空的 —— 库里那条设定的 id
    不在手上（materials 里的大纲与人物只有文本）。唯一键是
    (changeId, targetType, targetId, reasonKind)，同一个 changeId 下同章两处同类偏离会撞键丢掉
    一条，各自成组反而更清楚。
    """
    rows = []
    for conflict in conflicts:
        name = conflict["targetName"] or "未命名"
        target_type = conflict["targetType"]
        rows.append({
            "changeId": uuid.uuid4().hex,
            "changeSummary": f"第 {order} 章保留的偏离：《{name}》",
            "sourceType": "chapter",
            "sourceId": "",              # 这一章还没落库，此刻还没有 id
            "oldValue": conflict["rule"],
            "newValue": conflict["want"],
            "targetType": target_type,   # reader 已过白名单（见 reader._CONFLICT_TYPES）
            "targetId": "",
            "targetChapter": order,
            "reasonKind": "outline_conflict" if target_type == "outline" else "plot_conflict",
            "reason": (
                f"你要的写法跟《{name}》对不上：库里是「{conflict['rule'] or '（没写清）'}」，"
                f"你要「{conflict['want'] or '（没写清）'}」，你确认按自己的写。"
            ),
            "severity": "review",
            "detectedBy": "reader",
            # 用户当场就定了"不改正文"，所以不是待处理的 pending（见 utils/impact.py 的说明）。
            "status": "skipped",
            "resolution": _RESOLUTION,
        })
    return rows


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

    conflicts = list(state.get("chapter_conflicts") or [])

    if passed:
        head = f"第 {order} 章写完了（第 {attempt} 稿），审查这一关过了。"
    else:
        head = f"第 {order} 章写完了（第 {attempt} 稿），但审查这一关没过：\n\n{problems}"

    if conflicts:
        # 偏离跟"收不收下"并在一问里：答"保留"照样是收下，只是顺带把这几处记进受影响点。
        tail = (
            "保留这些写法（我记进受影响点），还是按库里改一版？"
            if passed
            else "要改的话，我照上面的意见和库里的口径一起改一版；就这样收下的话，"
                 "这几处偏离我给你记进受影响点。"
        )
        question = (
            f"{head}\n\n你要求的东西，跟库里这几处对不上：\n\n{_conflict_lines(conflicts)}"
            f"\n\n{tail}"
        )
    elif passed:
        question = f"{head}\n\n收下它、我这就存进这一章？要再改改的话，直接说往哪儿改。"
    else:
        question = f"{head}\n\n要我按这些意见改一版，还是就这样收下？要改的话说一句往哪儿改。"

    # 选项给前端做按钮。审查没过、或有偏离时才多一个"改"的出口 —— 其余情况收下是唯一去路。
    options = [{"id": "keep", "label": "收下并保留" if conflicts else "收下并保存"}]
    if conflicts or not passed:
        options.append({"id": "revise", "label": "按库里改" if conflicts else "按审查意见改"})

    answer = interrupt({"text": question, "options": options})

    # 按钮回传的选项认得出就照它定，不必再过模型；用户自己打字答的仍交给 KEEP_PROMPT 判
    # （它判的就是收下 / 要改 / 没表态 —— 只有前两样动流程，没表态的不当确认）。
    choice = _choice(answer)
    if choice:
        keep = choice == "keep"
        feedback = "" if keep else _redo_feedback(conflicts, problems if not passed else "")
    else:
        reply = await intentModel.ainvoke(
            [SystemMessage(content=KEEP_PROMPT), HumanMessage(content=str(answer or ""))]
        )
        text = reply.content if isinstance(reply.content, str) else ""
        keep, feedback = verdict(text, "keep")

    if keep:
        # review 一并改成"通过"再走：后面落库只认这一稿成没成，旧问题不带进去。
        # 状态留在 draft：收下只是"这稿存进这一章"，定不定稿由用户在前端自己标（完成 / 待修复）。
        # active_chapter 在父图是整份覆盖，交回去的必须是全量，漏了键就等于抹掉。
        update = {
            "active_chapter": {**chapter, "chapter_status": "draft"},
            "chapter_review": {"passed": True, "problems": ""},
            "edit_feedback": "",
        }
        # 偏离行只在用户点了保留时才记 —— 那是他拍板"就这么写下去"。将来回头改库里那几条设定
        # 时得知道有这么一章跟它对不上。落库在 update（setting_changes 为空、只有影响行也照写）。
        if conflicts:
            update["change_impact"] = _impact_rows(conflicts, order)
        return Command(goto="update", update=update)

    # 说得出"要改哪儿"才回炉（feedback 是用户原话，按钮那条已经替他说清了）。
    # chapter_review 原样留着：write 回炉靠 problems、edit 回炉靠 _is_redo（problems 或 feedback）。
    if feedback:
        target = "writer" if state.get("intension") == "write" else "editor"
        return Command(goto=target, update={"edit_feedback": feedback})

    # 既没说收下、也没说要改，多半是问了一句（"这里为什么这么写"）：这不是确认。
    # 先把这句话交给闲聊答了 —— chat 之后认得出这一稿还没落库，会转回这里把同一问再摆一次；
    # 正文一直留在 active_chapter 里，一个字都不会丢，也不会被没确认地存进库。
    # 他这句话**要写进 messages**：从前只写给 user_message（每轮被覆盖），这一问重摆时那半轮
    # 对话在历史里就断了（只有助手的答复、没有问的什么）；答完再回到这里，问题只由 interrupt
    # 摆出来，不再顶进问题正文，也就不必再去重。
    return Command(
        goto="chat",
        update={
            "user_message": str(answer or ""),
            "messages": [HumanMessage(content=str(answer or ""))],
        },
    )
