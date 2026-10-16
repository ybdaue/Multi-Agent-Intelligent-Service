"""reader 审完 → 无论通过与否都停下来问用户，收下才落库。write / edit 共用这一问。

取代原来的 ask_fix：那时只有 edit 这条路会停下来（新章是静默回炉，回炉次数用完静默收下）。
回炉目标按 intension 分，两条路的回炉机制各自是现成的：
  write → writer，_briefing 见 chapter_review 的 problems 或 edit_feedback 就走 _retry_note
  edit  → editor，_is_redo 见这两样就走 _redo_plan
判断"要不要改"复用 utils.verdict 与 KEEP_PROMPT（它判的就是收下 / 要改 / 不要了 / 没表态）。

**只有点按钮、或明说要收下，才算确认**。用户没点按钮、而是问了一句（"这里为什么这么写"）
时，那一句算没表态：先转给 chat 把话答了（chat 之后认得出这一稿还没落库，转回这里再问一次），
正文一直留在 active_chapter 里 —— 从前"没表态就当收下"的老口径会让一次普通的提问把稿子
静默落库（他没确认，库里的正文却已经换成了这一稿）。

用户这一轮的要求跟库里对不上的那几处（reader 的 chapter_conflicts）也并进这一问一起定夺：
他说保留就照他的写，那几处偏离记成影响台账（落库在 update）；说按库里改就回炉。前端把这三个
出口做成按钮（收下 / 按库里改 / 这一稿不要了），答复是 {"option": "keep" / "revise" / "discard"}，
认得出就不必再过模型。第三个出口是"反悔"：正文一个字都不落库，库里照旧。
"""
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt

from agents.utils.models import parse_json_value
from ..state import ChapterConflict, State
from ..utils.history import last_reply
from ..utils.model import intentModel, _intentModel_backup
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
    if isinstance(value, dict) and value.get("option") in ("keep", "revise", "discard"):
        return str(value["option"])
    return ""


def _said_discard(text) -> bool:
    """模型判词里"这一稿不要了"那个记号（见 KEEP_PROMPT 第 4 条）。打字答的那条路要靠它。"""
    try:
        value = parse_json_value(str(text or ""))
    except ValueError:
        return False
    return isinstance(value, dict) and value.get("discard") is True


def _discard(chapter: dict, order) -> Command:
    """这一稿不要了：正文一个字都不落库，本轮照常收尾。

    active_chapter 的正文清空 —— update 只认"正文非空、chapter_id 为空"才是本轮要落的稿，
    清空它就什么都不写（跨轮留着的 active_chapter 与正常落完库同形：正文空、章号还在）。
    审查结论 / 影响台账 / 设定改动一并清掉再交回去：reader 审出的问题行就摆在 change_impact
    里，留着会被 update 当成本轮的要落库的写进去。回话由 update 说（它写完 messages 自己把
    这个记号清掉）。
    """
    return Command(
        goto="update",
        update={
            "active_chapter": {**chapter, "chapter_content": ""},
            "chapter_review": {},
            "edit_feedback": "",
            "chapter_conflicts": [],
            "change_impact": [],
            "setting_changes": [],
            "edit_note": (
                f"第 {order} 章这一稿不要了，库里没动。想重写随时说一句。"
                if order
                else "这一稿不要了，库里没动。想重写随时说一句。"
            ),
        },
    )


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
    review_enabled = state.get("review_enabled", True)
    problems = (review.get("problems") or "").strip() or "审查这一关没过，但没写出具体问题。"

    conflicts = list(state.get("chapter_conflicts") or [])
    grade = state.get("change_grade") or ""
    # 用户这一轮要的是"改"就说"改好了"，说"写完了"像答错了（人工改稿与 agent 改稿都算改）。
    verb = "改好了" if state.get("intension") == "edit" else "写完了"
    # 这一问是"用户问了一句、由 chat 答完"之后重摆的（confirm_chapter → chat → 回到这里）。
    # 重摆时点一句"回到这一稿"，否则同一整段连着出现两次，看着像新的一问。判据是 messages 末尾
    # 那条助手回话：第一次摆时末尾是本轮那条用户消息（intension 写的），没有助手回话。
    back = "回到这一稿 —— " if last_reply(state.get("messages")) else ""

    if passed:
        # 审稿关掉的书没有"审查这一关"；L1 被跳过审稿、L2 只跑了两路 —— 别对它们谎称一句
        # 不存在的"过关"，走了哪一关就照实说哪一关。
        if not review_enabled:
            head = f"第 {order} 章{verb}（第 {attempt} 稿）。"
        elif grade == "L1":
            head = (
                f"第 {order} 章{verb}（第 {attempt} 稿）。"
                "这一稿是纯文字润色、没动事实，没走审稿。"
            )
        elif grade == "L2":
            head = f"第 {order} 章{verb}（第 {attempt} 稿），连贯性与人物设定这两关过了。"
        else:
            head = f"第 {order} 章{verb}（第 {attempt} 稿），审查这一关过了。"
    else:
        head = f"第 {order} 章{verb}（第 {attempt} 稿），但审查这一关没过：\n\n{problems}"

    head = f"{back}{head}"

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

    # 审稿关掉的书：这一稿没走 reader，收下前得把风险说清楚 —— 用户点"收下"时心里有数。
    if not review_enabled:
        question += (
            "\n\n注意：这本小说关掉了 AI 审稿 —— 这一稿没经过连贯性 / 人物设定 / 文风检查，"
            "直接收下入库有风险。"
        )

    # 选项给前端做按钮。审查没过、或有偏离时才多一个"改"的出口；"这一稿不要了"恒在 —— 它是
    # 中途反悔的路：没有它，用户只能收下或回炉，两条都得把这一稿走完。
    options = [{"id": "keep", "label": "收下并保留" if conflicts else "收下并保存"}]
    if conflicts or not passed:
        options.append({"id": "revise", "label": "按库里改" if conflicts else "按审查意见改"})
    options.append({"id": "discard", "label": "这一稿不要了"})

    answer = interrupt({"text": question, "options": options})

    # 按钮回传的选项认得出就照它定，不必再过模型；用户自己打字答的仍交给 KEEP_PROMPT 判
    # （它判的就是收下 / 要改 / 不要了 / 没表态 —— 前三样动流程，没表态的不当确认）。
    choice = _choice(answer)
    if choice == "discard":
        return _discard(chapter, order)
    if choice:
        keep = choice == "keep"
        feedback = "" if keep else _redo_feedback(conflicts, problems if not passed else "")
    else:
        try:
            reply = await intentModel.ainvoke(
                [SystemMessage(content=KEEP_PROMPT), HumanMessage(content=str(answer or ""))]
            )
        except Exception:
            try:
                reply = await _intentModel_backup.ainvoke(
                    [SystemMessage(content=KEEP_PROMPT), HumanMessage(content=str(answer or ""))]
                )
            except Exception:
                # 备用也失败时视为收下，不阻塞用户
                update = {
                    "active_chapter": {**chapter, "chapter_status": "draft"},
                    "chapter_review": {"passed": True, "problems": ""},
                    "edit_feedback": "",
                }
                if conflicts:
                    # reader 已把审出的问题行写进 state；这里追加偏离行，别把它覆盖掉。
                    update["change_impact"] = (
                        list(state.get("change_impact") or []) + _impact_rows(conflicts, order)
                    )
                return Command(goto="update", update=update)
        text = reply.content if isinstance(reply.content, str) else ""
        keep, feedback = verdict(text, "keep")
        # 他打字说"这一稿不要了"（按钮那条在上面就走掉了，落不到这儿）：别当成没表态。
        if not keep and _said_discard(text):
            return _discard(chapter, order)

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
            # 保留 state 里 reader 写的审查问题行，再把这几处偏离追加上去。
            update["change_impact"] = (
                list(state.get("change_impact") or []) + _impact_rows(conflicts, order)
            )
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
