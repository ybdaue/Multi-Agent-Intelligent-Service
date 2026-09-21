"""改已存在的内容：读懂要改什么 → 定夺是并进哪条还是新增 → 列出可能受影响的 → 用户点头 →
改 → 交回父图。

八个节点：prepare 备料（回炉这一趟顺手整理好计划）、plan 出 JSON 计划、settle 定夺设定这一轮
是并进已有的哪一条还是新增一条（只有设定这一路走它）、impact 定位并算范围、approve 摆给用户
点头、revise 改正文、collect 收稿、summarize 刷新摘要。
editor 一个字都不落库，设定改动、影响台账、正文都由父图的 update 写（正文落库前还要过 reader
的审）。改哪一处、要不要问用户、下一步去哪都是必要流程，全在图里，模型只干三件事：读懂要改
什么、定夺并进还是新增、把正文改出来。

plan 与 settle 的分工是这次改出来的：plan 只看得到目录（id + 名字），看不见内容，让它挑一条
去改就是"挑一条最像的顶上去" —— 用户说"补充世界观"，它会把原有的那条盖掉。所以设定这一路
plan 只认类型 + 复述诉求，settle 把这一类现有的全部内容摆出来再定，撞不上就新增。

章节类把 chapter_id 置空当"本轮新交稿"的记号（reader 与 update 都认，跟 writer 的 save 同口径），
身份由 (novelId, order) 认，落库时 UPSERT 按这两列冲突更新、原 id 带回来。
子图对话不上交父图（父图 messages 后面要整段交给 intension / chat）。
"""
import uuid
from typing import Annotated, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from agents.utils.models import parse_json_value
from ..state import ChapterMeta, ChapterReview, ChapterTarget, NovelMeta, merge_chapter
from ..tools import fetchDB, read_skill_file
from ..utils.chapter_information import (
    chapter_title,
    count_chapter_words,
    get_chapter,
    get_writer_context,
    list_chapters,
)
from ..utils.impact import (
    EDIT_SPEC,
    collect_chapter_impact,
    collect_impact,
    collect_new_impact,
    column_label,
    editable_fields,
    exists_by_key,
    field_notes,
    find_target,
    list_entries,
    render_change,
    render_entries,
    render_rows,
)
from ..utils.ledger import (
    NEW_ENTITY_SPEC,
    TYPE_LABEL,
    fetch_catalog,
    normalize_new,
    parse_ledger,
    split_submission,
)
from ..utils.model import MainModel, intentModel
from ..utils.prompt import APPROVE_PROMPT, EDIT_CHAPTER_PROMPT, EDIT_PLAN_PROMPT, SETTLE_PROMPT
from ..utils.verdict import verdict
from .writer import summarize


class EditorInput(TypedDict):
    """父图传进来的：小说设定、上一轮留在 state 里的章节、reader 的意见、用户的原话、上一轮的影响行。

    change_impact 也投进来：回炉重改是同一处改动，上一轮算好的影响行要接着用（见 _carried_impact）。
    target_chapter 是这一轮钉住的章节（请求里的 chapterId，intension 解析的）；named_chapter_order
    是他话里点名的章号，plan 拿这两个比一比，对不上就不动手。
    """

    novel: NovelMeta
    active_chapter: ChapterMeta
    chapter_review: ChapterReview
    target_chapter: ChapterTarget
    named_chapter_order: int
    edit_feedback: str
    user_message: str
    change_impact: list


class EditorOutput(TypedDict):
    """交回父图的：改出来的这一章（改设定的那一路不动它）、这次改动与它的影响台账、给人的回话。"""

    active_chapter: ChapterMeta
    setting_changes: list
    change_impact: list
    edit_note: str


class EditorState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    novel: NovelMeta
    active_chapter: Annotated[ChapterMeta, merge_chapter]
    chapter_review: ChapterReview
    target_chapter: ChapterTarget   # 这一轮钉住的章节（请求里的 chapterId）
    named_chapter_order: int        # 他话里点名的章号，plan 拿它跟 target_chapter 比
    edit_feedback: str
    user_message: str
    materials: str              # 给 plan 的：设定目录 + 章节清单
    prev_past_summary: dict     # 给 summarize 的：上一章留下的前文总结，要并进新版
    redo: bool                  # 回炉这一趟：目标与"用户同意"都是现成的，不用再问
    plan: dict                  # 这一轮要改什么：plan 出类型与诉求，settle 补上 mode/targetId/fields
    target: dict                # 定位到的目标：设定那一行（含旧值）或章节那一行（含原稿）；新增的没有
    setting_changes: list       # 设定类要写的列（新增的整条），update 落库
    change_impact: list         # 影响台账的行，update 落库
    approve_text: str           # 摆给用户看的"改动 + 影响范围"
    edit_note: str              # 没改成的理由，update 拿它回用户一句话


# 计划与判词都是小提示词 + JSON 出参，不需要工具循环，直接调模型。temperature 要稳定判断。
_editModel = MainModel(temperature=0.1, disable_streaming=True)

# 改稿照 writerSkill 写，挂跟 writer 一样的两件工具。问用户是 approve 的事，不挂工具；
# 也不挂"交稿"工具（正文与台账就是模型的回复，切开与落 state 是 collect 的事）。
# 开着流式：改出来的正文要逐字发给前端当打字机。台账由 api/novel/stream.py 的
# ProseFilter 在【本章台账】处截掉（与 writer 共用同一套标记与规则）。
_revise_agent = create_agent(
    model=MainModel(temperature=0.7, disable_streaming=False),
    tools=[read_skill_file, fetchDB],
    system_prompt=EDIT_CHAPTER_PROMPT,
    state_schema=EditorState,
)


def _last_reply(messages) -> str:
    """最后一条没有工具调用的助手回复 —— 改稿交上来的就是它。"""
    for message in reversed(messages or []):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            content = message.content
            if isinstance(content, str) and content.strip():
                return content
    return ""


def _is_chapter(state: EditorState) -> bool:
    return (state.get("plan") or {}).get("targetType") == "chapter"


def _is_redo(state: EditorState) -> bool:
    """这一趟是不是回炉：reader 审出了硬伤，或者用户在 ask_fix 里给了答复。"""
    review = state.get("chapter_review") or {}
    problems = "" if review.get("passed", True) else (review.get("problems") or "").strip()
    return bool(problems or (state.get("edit_feedback") or "").strip())


def _fresh_draft(state: EditorState, order: int) -> dict | None:
    """state 里这一轮刚改出来的那一稿（chapter_id 空 = 本轮新交稿）。

    回炉时拿它当原稿：它比库里的新。
    """
    chapter = state.get("active_chapter") or {}
    if chapter.get("chapter_order") == order and not chapter.get("chapter_id"):
        return chapter
    return None


def _carried_impact(state: EditorState, source_id: str) -> list[dict]:
    """上一轮为**同一处**改动算出来的影响行（sourceId 认的是被改的那一行）。

    回炉还是改同一章，影响范围一模一样；换一个 changeId 重算，用户在清单里就会看到"同一处报了两次"。
    """
    rows = state.get("change_impact") or []
    if rows and rows[0].get("sourceId") == source_id:
        return rows
    return []


def _redo_plan(state: EditorState) -> dict:
    """回炉这一趟的计划：目标就是刚交的这一章，要求 = 审查意见 + 用户的答复，不再问模型。"""
    chapter = state.get("active_chapter") or {}
    order = chapter.get("chapter_order")
    review = state.get("chapter_review") or {}
    problems = (review.get("problems") or "").strip()
    feedback = (state.get("edit_feedback") or "").strip()

    lines = []
    if problems:
        lines.append(f"审查审出来的问题：\n{problems}")
    if feedback:
        lines.append(f"用户的答复：\n{feedback}")
    return {
        "targetType": "chapter",
        "chapterOrder": order,
        "summary": f"按审查意见再改一次第 {order} 章",
        "instruction": "\n\n".join(lines) or "按上一轮的审查意见再改一次这一章",
        "note": "",
    }


def _plan_brief(state: EditorState) -> str:
    """交给 plan 的：用户原话 + 设定目录 + 章节清单，外加用户对上一版方案的意见。

    还得说他这会儿正看着哪一章 —— 只说"把这一章改一下"时，模型据此才知道"这一章"是第几章，
    写 instruction 才写得对。改哪一章它说了不算，章号由 plan 那边按 target_chapter 填死。
    """
    lines = [f"用户这一轮说：\n\n{(state.get('user_message') or '').strip()}"]

    feedback = (state.get("edit_feedback") or "").strip()
    if feedback:
        lines.append(f"（他看过上一版方案之后又说：{feedback}）")

    order = (state.get("target_chapter") or {}).get("chapter_order")
    if order:
        lines.append(f"（他这会儿正开着第 {order} 章 —— 要改的就是这一章，你说改成什么样就行。）")

    lines.append(state.get("materials") or "")
    return "\n\n".join(line for line in lines if line)


def _context_brief(context: dict, order: int) -> str:
    """改这一章要对着看的：本章生效的大纲与世界规则、上一章全文、前文总结、设定目录。

    原稿不在这儿 —— 它单独摆在最后，免得模型把"要改的稿"和"参照物"看混。
    """
    lines = []

    outlines = [text for text in (context.get("outlines") or []) if text.strip()]
    if outlines:
        lines.append("本章生效的大纲：\n\n" + "\n\n".join(outlines))

    world_rules = context.get("world_rules") or []
    if world_rules:
        rules = "\n".join(f"- {r['name']}：{r['rule']}" for r in world_rules)
        lines.append(f"本章生效的世界规则、力量体系，改出来的东西别跟它们打架：\n{rules}")

    prev_content = (context.get("prev_content") or "").strip()
    if prev_content:
        lines.append(f"上一章（第 {order - 1} 章）全文：\n\n{prev_content}")

    past_summary = context.get("prev_past_summary") or {}
    past_text = (past_summary.get("text") or "").strip() if isinstance(past_summary, dict) else ""
    if past_text:
        lines.append(f"到第 {order - 1} 章为止的前文总结：\n\n{past_text}")

    catalog = (context.get("catalog") or "").strip()
    if catalog:
        lines.append(
            "库里已有的设定目录（每行是「id 名字」，末尾台账报 ref 时照它给 id）：\n\n" + catalog
        )
    return "\n\n".join(lines)


def _revise_brief(state: EditorState, plan: dict, draft: dict, context: dict, order: int) -> str:
    """交给改稿 agent 的：改第几章、怎么改、这一章的前文与设定、原稿全文。"""
    lines = [f"请改第 {order} 章《{draft.get('chapter_title') or '未命名'}》，不是新写一章。"]

    instruction = (plan.get("instruction") or "").strip()
    if instruction:
        lines.append(f"用户的要求：\n\n{instruction}")

    reference = _context_brief(context, order)
    if reference:
        lines.append(reference)

    lines.append(
        f"这一章现在的原稿全文如下，**没让改的地方逐字保留**：\n\n"
        f"{draft.get('chapter_content') or ''}"
    )
    lines.append("改完把整章、连同末尾的「【本章台账】」一起发回来。")
    return "\n\n".join(lines)


def _setting_notes(old_fields: dict, fields: dict) -> list[str]:
    """给人看的"改了哪几列"：旧值 → 新值，一行一列。"""
    lines = []
    for column, value in fields.items():
        old = str(old_fields.get(column) or "")
        if value == old:
            continue
        lines.append(f"- {column_label(column)}：{old or '（空）'} → {value or '（空）'}")
    if not lines:
        return []
    return ["改动内容：\n" + "\n".join(lines)]


async def prepare(state: EditorState, config: RunnableConfig) -> dict:
    """守卫 + 备料；回炉这一趟顺手整理好计划，后面就不走 plan 了。"""
    novel_id = (config.get("configurable") or {}).get("novel_id")
    if not novel_id:
        return {"edit_note": "拿不到当前这本书的编号，改不了。"}

    novel = state.get("novel") or {}
    catalog = (await fetch_catalog(novel_id)).strip()
    chapters = (await list_chapters(novel_id)).strip()

    blocks = [f"《{novel.get('novel_title') or '未命名'}》"]
    blocks.append(
        "库里已有的设定目录（每行是「id 名字」，认类型用；具体内容下一步才摆出来）：\n\n" + catalog
        if catalog
        else "库里还没有任何设定。"
    )
    blocks.append(
        "这本书已有的章节：\n\n" + chapters if chapters else "这本书还没有章节，没有可改的章节。"
    )
    materials = "\n\n".join(blocks)

    chapter = state.get("active_chapter") or {}
    if _is_redo(state) and chapter.get("chapter_order") and not chapter.get("chapter_id"):
        return {"materials": materials, "redo": True, "plan": _redo_plan(state)}
    return {"materials": materials, "redo": False}


def _route_after_prepare(state: EditorState) -> str:
    """回炉计划已备好就直接去 impact；正常这一趟先让模型读懂用户要改什么。"""
    return "impact" if state.get("plan") else "plan"


def _conflict_text(said: int, order: int) -> str:
    """他话里点名的章和他开着的那一章对不上时的回话。

    改正文就得改库里那一行，章号不能由模型认、也不能将就着改错那一章，所以不猜，请他先切过去。
    """
    return (
        f"你说的第 {said} 章，和你这会儿开着的第 {order} 章对不上。"
        f"我这边只认你正开着的那一章 —— 要改哪一章，先切到那一章，再跟我说。"
    )


async def plan(state: EditorState, config: RunnableConfig) -> dict:
    """读懂用户要改什么、改成什么；出不来计划就写一句回话，这一轮什么都不改。"""
    reply = await _editModel.ainvoke(
        [SystemMessage(content=EDIT_PLAN_PROMPT), HumanMessage(content=_plan_brief(state))]
    )
    text = reply.content if isinstance(reply.content, str) else ""
    try:
        value = parse_json_value(text)
    except (ValueError, TypeError):
        value = {}
    if not isinstance(value, dict):
        value = {}

    target_type = str(value.get("targetType") or "").strip()
    note = str(value.get("note") or "").strip()
    if not target_type:
        return {
            "plan": {},
            "edit_note": note or "我没听懂要改哪一处。你说清改什么、改成什么，我再动手。",
        }

    if target_type == "chapter":
        # 章号一律取这一轮钉住的那一章（请求里的 chapterId，intension 钉的），模型报什么都不作数。
        order = (state.get("target_chapter") or {}).get("chapter_order")
        if not order:
            # 没钉住 = 他开着的那一章还不在库里（本地新建、还没写出来），没有正文可改。
            return {"plan": {}, "edit_note": "你在的这一章还没写出来，先让它写出来再改。"}
        # 他话里点了别的章号：不动手，请他切过去。改的必须是库里那一行，不能靠模型认。
        if (said := state.get("named_chapter_order")) and said != order:
            return {"plan": {}, "edit_note": _conflict_text(said, order)}
        value["chapterOrder"] = int(order)
        return {"plan": value}

    if target_type not in EDIT_SPEC:
        return {"plan": {}, "edit_note": f"「{target_type}」这类东西改不了。"}

    # 设定这一路只交类型与诉求：改哪几列、是并进已有的一条还是新增，都由 settle 拿着这一类
    # 现有的内容去定 —— 模型从"补充世界观"里挑出来的那一行，正是要被盖掉的那一行。
    return {"plan": {
        "targetType": target_type,
        "summary": str(value.get("summary") or "").strip(),
        "request": str(value.get("request") or "").strip(),
        # 只是线索（照目录抄的名字），不是"就改这一条"的结论：settle 靠它把这一条先捞出来看，
        # 条目多到清单装不下时才不至于漏掉用户点名的那一条。
        "targetName": str(value.get("targetName") or "").strip(),
        "note": note,
    }}


def _route_after_plan(state: EditorState) -> str:
    """出得来计划：设定这一路先去 settle 定夺，章节那一路直接去算范围；出不来就收工。"""
    if not state.get("plan"):
        return "done"
    return "impact" if _is_chapter(state) else "settle"


def _settle_brief(state: EditorState, plan: dict, entries: str) -> str:
    """交给 settle 的：用户原话 + 这一类设定的全部现有内容。

    原话要摆，不只摆 plan 复述的那句 —— settle 是唯一拍板"并进还是新增"的地方，宁可让它
    读用户自己说的字。清单为空也要说清楚，不然模型可能以为漏给了材料。
    """
    target_type = str(plan.get("targetType") or "")
    label = TYPE_LABEL.get(target_type, target_type)
    lines = [f"用户这一轮说：\n\n{(state.get('user_message') or '').strip()}"]

    request = (plan.get("request") or "").strip()
    if request:
        lines.append(f"（上一轮的理解：{request}）")

    if entries:
        lines.append(f"库里现有的【{label}】，一条一版：\n\n{entries}")
    else:
        lines.append(f"库里现在一条【{label}】都没有，这一轮只可能是新增。给出一条新的就按新增回。")
    return "\n\n".join(lines)


async def settle(state: EditorState, config: RunnableConfig) -> dict:
    """设定这一路：拿这一类现有的全部内容跟用户要补的东西比一遍，定夺并进哪一条、还是新增。

    全图唯一产出 fields 的地方，也是唯一决定 update 还是 create 的地方。清单里的内容看得到
    才谈得上"冲突了才覆盖、且只覆盖冲突那几列"—— plan 拿着目录挑一条，挑的就是要被盖掉的那条。
    """
    novel_id = (config.get("configurable") or {}).get("novel_id")
    plan = state.get("plan") or {}
    target_type = str(plan.get("targetType") or "")

    entries = await list_entries(novel_id, target_type, str(plan.get("targetName") or "").strip())
    reply = await _editModel.ainvoke(
        [
            SystemMessage(content=SETTLE_PROMPT),
            HumanMessage(content=_settle_brief(state, plan, render_entries(target_type, entries))),
        ]
    )
    text = reply.content if isinstance(reply.content, str) else ""
    try:
        value = parse_json_value(text)
    except (ValueError, TypeError):
        value = {}
    if not isinstance(value, dict):
        value = {}

    mode = str(value.get("mode") or "").strip()
    note = str(value.get("note") or "").strip()
    summary = str(value.get("summary") or "").strip() or (plan.get("summary") or "")
    label = TYPE_LABEL.get(target_type, target_type)

    if mode == "create":
        # 大纲这类不在 NEW_ENTITY_SPEC 里的只能改、不能新增（开书时就定死了）。
        if target_type not in NEW_ENTITY_SPEC:
            return {"plan": {}, "edit_note": f"【{label}】不能新增，只能改已有的那几条。"}
        # 新增的字段过 NEW_ENTITY_SPEC：白名单 + 缺列补默认值（status 就是这么补上的）。
        # 改的那条路走 EDIT_SPEC（不含 status），两条路用的白名单本就不是一份。
        created = normalize_new([{"refType": target_type, "fields": value.get("fields")}])
        if not created:
            return {"plan": {}, "edit_note": note or "没看出这条新设定叫什么，你说清我再加。"}
        fields = created[0]["fields"]
        name = fields[NEW_ENTITY_SPEC[target_type]["key"]]
        # 清单刚摆给它看过还报新增，说明它自相矛盾：插一条重复的、或盖到原来那条上都不能干。
        if await exists_by_key(novel_id, target_type, name):
            return {
                "plan": {},
                "edit_note": f"库里已经有一条《{name}》了。要把它改成你说的这样，还是另起一条、换个名字？",
            }
        return {"plan": {
            **plan, "mode": "create", "targetId": "", "targetName": name,
            "summary": summary, "fields": fields,
        }}

    if mode == "update":
        fields = editable_fields(target_type, value.get("fields"))
        if not fields:
            return {"plan": {}, "edit_note": note or "没看出你要把这一条的哪一列改成什么，说具体一点。"}
        return {"plan": {
            **plan, "mode": "update",
            "targetId": str(value.get("targetId") or "").strip(),
            "targetName": str(value.get("targetName") or "").strip(),
            "summary": summary, "fields": fields,
        }}

    return {"plan": {}, "edit_note": note or f"没看出你要加的是哪一条{label}，说具体一点。"}


def _route_after_settle(state: EditorState) -> str:
    """定夺完就去算范围；定不下来（plan 已清空、回话写在 edit_note 里）就收工。"""
    return "impact" if state.get("plan") else "done"


async def _new_setting(
    novel_id: str, plan: dict, target_type: str, change_id: str, summary: str
) -> dict:
    """新增一条设定：落库前把"正文里已经写过它"的章节挑出来，摆给用户看。

    它还没被哪一章的台账报过（那要等 writer 下一次写），字面匹配是眼下唯一的线索 ——
    不查这一下，approve 摆出来的"没查到波及"就是一句假的安心。
    """
    spec = NEW_ENTITY_SPEC.get(target_type)
    fields = plan.get("fields") or {}
    label = TYPE_LABEL.get(target_type, target_type)
    if spec is None or not fields:
        return {"plan": {}, "edit_note": f"没看出要新增的是哪一条{label}。"}

    name = str(fields.get(spec["key"]) or "").strip() or str(plan.get("targetName") or "").strip()
    name = name or "（未命名）"
    rows = await collect_new_impact(
        novel_id, change_id=change_id, change_summary=summary, ref_type=target_type, fields=fields
    )

    # 不走 render_change：它没有影响行时会打"没查到可能被波及的地方"，对新增是误导。
    blocks = [
        f"我要新增一条【{label}】《{name}》，库里现在没有这一条。",
        f"新增内容：\n{field_notes(fields)}",
    ]
    if rows:
        blocks.extend(render_rows(rows))
        blocks.append(f"上面这些是正文里已经写过「{name}」的章节，要不要动由你定。")
    else:
        blocks.append(f"正文里还没有哪一章提到过「{name}」，眼下没有要回头对的地方。")
    return {
        "target": {},
        "setting_changes": [
            {"mode": "create", "refType": target_type, "refId": "", "fields": fields}
        ],
        "change_impact": rows,
        "approve_text": "\n\n".join(blocks),
    }


async def impact(state: EditorState, config: RunnableConfig) -> dict:
    """定位目标、取旧行、比差异、算范围。全是确定性的，一处语义判断都没有。"""
    novel_id = (config.get("configurable") or {}).get("novel_id")
    plan = state.get("plan") or {}
    change_id = uuid.uuid4().hex
    summary = (plan.get("summary") or "").strip() or "这次改动"

    if _is_chapter(state):
        order = plan.get("chapterOrder")
        row = await get_chapter(novel_id, order)
        if row is None:
            return {"plan": {}, "edit_note": f"库里没有第 {order} 章，改不了。"}

        # 原稿取更新的一版：回炉时 state 里那一稿比库里的新。
        draft = _fresh_draft(state, order) or row
        context = await get_writer_context(novel_id, order)
        # 同一处改动重算没意义，认得上就用上一轮那批（连同它的 changeId）。
        rows = _carried_impact(state, row["chapter_id"]) or await collect_chapter_impact(
            novel_id,
            change_id=change_id,
            change_summary=summary,
            chapter_id=row["chapter_id"],
            order=order,
        )
        return {
            "target": row,
            "prev_past_summary": context.get("prev_past_summary") or {},
            "setting_changes": [],
            "change_impact": rows,
            # 改的是哪一章得写清：它由请求里的 chapterId 定（用户当时开着那一章），不是这句话里
            # 说的；他中途翻去别处再回来，得凭这一行认出改的到底是哪一章。
            "approve_text": (
                f"要改的是第 {order} 章《{row.get('chapter_title') or '未命名'}》。\n\n"
                + render_change(summary, [], rows)
            ),
            "messages": [HumanMessage(content=_revise_brief(state, plan, draft, context, order))],
        }

    target_type = str(plan.get("targetType") or "")
    spec = EDIT_SPEC.get(target_type)
    if spec is None:
        return {"plan": {}, "edit_note": f"「{target_type}」这类东西改不了。"}

    if plan.get("mode") == "create":
        return await _new_setting(novel_id, plan, target_type, change_id, summary)

    fields = editable_fields(target_type, plan.get("fields"))
    if not fields:
        return {"plan": {}, "edit_note": "没看出你要把哪一列改成什么，说具体一点。"}

    target = await find_target(
        novel_id,
        target_type,
        str(plan.get("targetId") or "").strip(),
        str(plan.get("targetName") or "").strip(),
    )
    if target is None:
        wanted = plan.get("targetName") or plan.get("targetId") or "那一条"
        return {"plan": {}, "edit_note": f"库里没找到要改的{wanted}，你说清是哪一个。"}

    old_fields = target["fields"]
    if all(str(old_fields.get(column) or "") == value for column, value in fields.items()):
        return {"plan": {}, "edit_note": "要改的这几列跟库里现在的一模一样，没什么可改的。"}

    rows = await collect_impact(
        novel_id,
        change_id=change_id,
        change_summary=summary,
        ref_type=target_type,
        target_id=target["id"],
        old_fields=old_fields,
        new_fields=fields,
    )
    notes = _setting_notes(old_fields, fields)
    return {
        "target": target,
        "setting_changes": [
            {"mode": "update", "refType": target_type, "refId": target["id"], "fields": fields}
        ],
        "change_impact": rows,
        "approve_text": render_change(summary, notes, rows),
    }


def _route_after_impact(state: EditorState) -> str:
    """impact 之后：没计划就收工；回炉这一趟用户已经同意过了，直接改；正常这一趟先摆给用户看。"""
    if not state.get("plan"):
        return "done"
    return "revise" if state.get("redo") else "approve"


async def approve(state: EditorState, config: RunnableConfig) -> dict:
    """把"要改什么 + 可能波及哪些"摆给用户，等他点头。

    interrupt 之前只读 state：节点恢复时会从头重跑，写在它前面的副作用会走两遍。
    """
    answer = interrupt(
        f"{state.get('approve_text') or ''}\n\n"
        "同意就说一声，我这就动手；要换一处改、或者要改成别的样子，直接说。"
    )
    reply = await intentModel.ainvoke(
        [SystemMessage(content=APPROVE_PROMPT), HumanMessage(content=str(answer))]
    )
    text = reply.content if isinstance(reply.content, str) else ""
    go, feedback = verdict(text, "go")

    if go:
        return {"plan": state.get("plan") or {}}
    # impact 摆下的改动与影响台账得撤掉：它们会经 output_schema 交给 update，
    # 留着就等于用户说了不改、回头还是改了。
    return {
        "plan": {},
        "setting_changes": [],
        "change_impact": [],
        "edit_feedback": "",
        "edit_note": feedback or "没看出你同不同意，这次先不动。你要改就说清改成什么样。",
    }


def _route_after_approve(state: EditorState) -> str:
    """点头了：改章节的继续去改，改设定的到此为止（update 会落库）；没点头就收工。"""
    if not state.get("plan"):
        return "done"
    return "revise" if _is_chapter(state) else "done"


def collect(state: EditorState, config: RunnableConfig) -> dict:
    """收这一稿：切正文与台账，其余字段沿用库里那一行，序号照旧（不新起一章）。"""
    row = state.get("target") or {}
    order = row.get("chapter_order")
    content = _last_reply(state.get("messages"))
    prose, ledger_text = split_submission(content)
    if not prose or not order:
        # 改稿没交上来，这次改动就没发生：影响台账一并撤掉，别让 update 当成"改过了"记进库。
        return {
            "plan": {},
            "setting_changes": [],
            "change_impact": [],
            "edit_note": "这一版没改出来（回复是空的），你再说一次要改哪里。",
        }

    # refs 可能是 None（没给台账）：落库时旧的关联一行不动，留着上一稿的。
    refs, new_entries = parse_ledger(ledger_text)
    return {
        "active_chapter": {
            "chapter_id": "",
            "chapter_title": chapter_title(prose) or row.get("chapter_title") or "未命名",
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
        }
    }


def _route_after_collect(state: EditorState) -> str:
    """收到稿子就去刷摘要；没收到（plan 已清空、写了回话）就收工。"""
    return "summarize" if state.get("plan") else "done"


_editor_flow = StateGraph(EditorState, input_schema=EditorInput, output_schema=EditorOutput)
_editor_flow.add_node("prepare", prepare)
_editor_flow.add_node("plan", plan)
_editor_flow.add_node("settle", settle)
_editor_flow.add_node("impact", impact)
_editor_flow.add_node("approve", approve)
_editor_flow.add_node("revise", _revise_agent)
_editor_flow.add_node("collect", collect)
_editor_flow.add_node("summarize", summarize)
_editor_flow.add_edge(START, "prepare")
# 备料之后往哪走、算完范围收工还是继续，都由节点定的条件边判，不由模型挑。
_editor_flow.add_conditional_edges("prepare", _route_after_prepare, {"plan": "plan", "impact": "impact"})
_editor_flow.add_conditional_edges(
    "plan", _route_after_plan, {"settle": "settle", "impact": "impact", "done": END}
)
_editor_flow.add_conditional_edges("settle", _route_after_settle, {"impact": "impact", "done": END})
_editor_flow.add_conditional_edges(
    "impact", _route_after_impact, {"approve": "approve", "revise": "revise", "done": END}
)
_editor_flow.add_conditional_edges(
    "approve", _route_after_approve, {"revise": "revise", "done": END}
)
_editor_flow.add_edge("revise", "collect")
_editor_flow.add_conditional_edges("collect", _route_after_collect, {"summarize": "summarize", "done": END})
_editor_flow.add_edge("summarize", END)

# 不带 checkpointer：挂进父图时就用父图那个，approve 的 interrupt 才能存下来。
editor = _editor_flow.compile(name="novel_editor")
