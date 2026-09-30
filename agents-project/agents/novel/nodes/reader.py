"""审稿：查档 → 核验 → 收结论，三步一条线。

先按 writer 报的台账把相关设定的原始档案取回来，再让审查 agent 对着正文查六类硬伤、
顺带跟库里的档案对一遍，最后 save 解析成 chapter_review。
档案是事实底座，审查员的 prompt 会先自问自答再交结论；判词真假与回炉还是落库由图边定。
同一趟里还要对着用户这一轮的原话查一遍：他要的写法跟库里记的对不上就记进
chapter_conflicts（那不是硬伤，是交用户定夺的一件事），父图 confirm_chapter 拿它问用户。
认「本轮新交稿」用 chapter_id 空不空（与 update 同口径）；子图对话不上交父图。
"""
from typing import Annotated, List, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agents.utils.models import ainvoke_with_fallback, parse_json_value
from ..state import ChapterConflict, ChapterMeta, ChapterReview, NovelMeta
from ..tools import fetchDB, read_skill_file
from ..utils.chapter_information import get_writer_context
from ..utils.ledger import fetch_ref_facts
from ..utils.model import BackupMainModel, MainModel
from ..utils.novel_information import render_protagonists
from ..utils.prompt import READER_PROMPT
from ..utils.trace import traced


class ReaderInput(TypedDict):
    novel: NovelMeta
    active_chapter: ChapterMeta
    user_message: str
    writer_context: dict                # resolve 预查的上下文，gather 复用跳过查库


class ReaderOutput(TypedDict):
    """交回父图的：这一稿的审查结论，和用户要求跟库里对不上的那几处。子图的材料与对话不上交。"""

    chapter_review: ChapterReview
    chapter_conflicts: List[ChapterConflict]


class _Chat(TypedDict, total=False):
    """审查 agent 的对话。只用来装它自己的消息，材料与结论都在外面。"""

    messages: Annotated[list[AnyMessage], add_messages]


class ReaderState(TypedDict, total=False):
    novel: NovelMeta
    active_chapter: ChapterMeta
    user_message: str
    materials: str                # gather 备好的设定与前文
    facts: str                    # 台账指向的那些行现在的档案
    report: str                   # check 交上来的原始判词
    chapter_review: ChapterReview
    chapter_conflicts: List[ChapterConflict]
    writer_context: dict          # resolve 预查的上下文，gather 复用跳过查库


# 审查要稳定判断，temperature 比 writer 低；不挂 run_skill_script（只读文档）、
# 不挂"交结论"工具（判词就是模型的回复，收结论是 save 的事）。
# disable_streaming：输出是给父图判路用的，不是给前端的。
try:
    _reader_main = MainModel(temperature=0.1, disable_streaming=True)
    _reader_main_backup = BackupMainModel(temperature=0.1, disable_streaming=True)
except Exception:
    _reader_main = None
    _reader_main_backup = None

_reader_agent = create_agent(
    model=_reader_main,
    tools=[read_skill_file, fetchDB],
    system_prompt=READER_PROMPT,
    state_schema=_Chat,
)

_reader_agent_backup = create_agent(
    model=_reader_main_backup,
    tools=[read_skill_file, fetchDB],
    system_prompt=READER_PROMPT,
    state_schema=_Chat,
)

_PASSED: ChapterReview = {"passed": True, "problems": ""}

# 冲突记的是"用户要的偏离了库里哪一类东西"。取值照 my-app/prisma/schema/novel.prisma 的
# ImpactTarget 抄，进库要按它查；认不出来的（模型写了中文、或写了 novel 这种不可能是冲突
# 对象的）一律不收 —— 收下来落库时枚举不过，整笔事务都会回滚。
_CONFLICT_TYPES = frozenset({
    "outline", "world_rule", "character", "faction", "item",
    "timeline", "chronicle", "foreshadowing",
})


def _last_reply(messages) -> str:
    """最后一条没有工具调用的助手回复 —— 审查结论就是它。"""
    for message in reversed(messages or []):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            content = message.content
            if isinstance(content, str) and content.strip():
                return content
    return ""


def _parsed(text: str) -> dict:
    """模型那段判词 JSON。解析不出来、不是个对象，都交空 dict，后面的判定各自兜底。"""
    try:
        value = parse_json_value(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _verdict(value: dict) -> ChapterReview:
    """从判词里取结论。passed 不是布尔就当通过 —— 卡死整轮比放过一章糟。"""
    if not isinstance(value.get("passed"), bool):
        return dict(_PASSED)
    problems = value.get("problems")
    return {
        "passed": value["passed"],
        "problems": problems if isinstance(problems, str) else "",
    }


def _conflicts(value: dict) -> List[ChapterConflict]:
    """从判词里取"用户要的跟库里对不上"的条目。

    只收认得出来的：类型得在白名单里，rule / want 得有一句能看的话。模型漏报、报歪都不耽误
    这一轮 —— 顶多少记一条台账，用户该看到的审查结论照样在。
    """
    rows = value.get("conflicts")
    if not isinstance(rows, list):
        return []
    out: List[ChapterConflict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        target_type = str(row.get("targetType") or "").strip()
        if target_type not in _CONFLICT_TYPES:
            continue
        out.append({
            "targetType": target_type,
            "targetName": str(row.get("targetName") or "").strip(),
            "rule": str(row.get("rule") or "").strip(),
            "want": str(row.get("want") or "").strip(),
        })
    return out


def _materials(state: ReaderState, context: dict) -> str:
    """审这一章要对着看的设定与前文。正文和摘要不在这里 —— check 现摆。"""
    novel = state.get("novel") or {}
    chapter = state.get("active_chapter") or {}
    order = chapter.get("chapter_order")
    lines = [
        f"《{novel.get('novel_title') or '未命名'}》；"
        f"小说套路：{novel.get('novel_tropes') or '未填'}；"
        f"小说风格：{novel.get('novel_style') or '未填'}。"
    ]

    protagonists = render_protagonists(novel)
    if protagonists:
        lines.append(f"主角人设（对着它查 OOC）：\n{protagonists}")

    outlines = [text for text in (context.get("outlines") or []) if text.strip()]
    if outlines:
        lines.append("本章生效的大纲，对着它查有没有跑偏：\n\n" + "\n\n".join(outlines))
    else:
        lines.append("库里还没有本章适用的大纲，这一项没得对，跳过。")

    world_rules = context.get("world_rules") or []
    if world_rules:
        rules = "\n".join(f"- {r['name']}：{r['rule']}" for r in world_rules)
        lines.append(f"本章生效的世界规则、力量体系，对着它查有没有写崩：\n{rules}")
    else:
        lines.append("库里还没有本章适用的世界规则，这一项没得对，跳过。")

    catalog = (context.get("catalog") or "").strip()
    if catalog:
        lines.append(
            "库里已有的设定目录（按类型分块，每行是「id 名字」，前面那串 id 不用管）：\n\n"
            f"{catalog}\n\n"
            "对着它查：本章里新登场的人物、势力、物品、规则，是不是其实库里早就有了 —— "
            "撞了名字，或者本来就是同一个东西，却被另起一个名字、另立一份地写了一遍。"
        )
    else:
        lines.append("库里还没有任何设定，目录是空的。")

    prev_content = (context.get("prev_content") or "").strip()
    if prev_content:
        lines.append(f"上一章（第 {order - 1} 章）全文，对着它查承接和事件有没有跳：\n\n{prev_content}")
    else:
        lines.append("这是本书第一章，没有上一章可接，承接这一项跳过。")

    prev_prev_summary = (context.get("prev_prev_summary") or "").strip()
    if prev_prev_summary:
        lines.append(f"上上一章（第 {order - 2} 章）的精简：\n\n{prev_prev_summary}")

    past_summary = context.get("prev_past_summary") or {}
    past_text = (past_summary.get("text") or "").strip() if isinstance(past_summary, dict) else ""
    if past_text:
        lines.append(f"到第 {order - 1} 章为止的前文总结：\n\n{past_text}")
    return "\n\n".join(lines)


def _check_briefing(state: ReaderState, materials: str, facts: str) -> str:
    """交给审查 agent 的：设定与前文、档案（含自问自答素材）、正文全文。"""
    chapter = state.get("active_chapter") or {}
    order = chapter.get("chapter_order")
    title = chapter.get("chapter_title") or "未命名"
    lines = [f"请审第 {order} 章《{title}》。"]

    summary = (chapter.get("chapter_summary") or "").strip()
    if summary:
        lines.append(f"本章摘要：\n\n{summary}")

    said = (state.get("user_message") or "").strip()
    if said:
        lines.append(f"用户对这一章的要求（他明确要的写法，可能跟下面库里的设定对不上）：\n\n{said}")

    lines.append(materials)

    if facts.strip():
        lines.append(
            "本章涉及的那些设定在库里的原始档案（库里现在的原样，不是正文里的说法）：\n\n"
            f"{facts.strip()}"
        )

    lines.append(f"要审的这一章正文全文如下：\n\n{chapter.get('chapter_content') or ''}")
    lines.append(
        "上面档案没覆盖到的设定（本章没用到、正文里却冒出来的），要核对就用 fetchDB 按名字点查"
        "那一条，别整表拉。"
    )
    return "\n\n".join(lines)


async def gather(state: ReaderState, config: RunnableConfig) -> dict:
    """备材料：复用 resolve 缓存的 writer_context，台账指向的档案按 refId 从库里取。"""
    chapter = state.get("active_chapter") or {}
    if not chapter.get("chapter_content") or chapter.get("chapter_id"):
        return {"chapter_review": dict(_PASSED)}

    novel_id = (config.get("configurable") or {}).get("novel_id")
    if not novel_id:
        return {"chapter_review": dict(_PASSED)}

    context = state.get("writer_context") or await get_writer_context(
        novel_id, chapter.get("chapter_order")
    )
    facts = await fetch_ref_facts(novel_id, chapter.get("chapter_refs"))
    return {"materials": _materials(state, context), "facts": facts}


def _route_after_gather(state: ReaderState) -> str:
    """gather 之后的去路：守卫拦下的收工，有档案先查，否则直接核验。"""
    if state.get("chapter_review"):
        return "done"
    return "check"


async def check(state: ReaderState, config: RunnableConfig) -> dict:
    """过六类硬伤 + 对照档案自问自答，交回原始判词。"""
    try:
        result = await _reader_agent.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=_check_briefing(
                            state,
                            state.get("materials") or "",
                            state.get("facts") or "",
                        )
                    )
                ]
            },
            config,
        )
    except Exception:
        print("[reader] 主审查 agent 失败，尝试备用")
        try:
            result = await _reader_agent_backup.ainvoke(
                {
                    "messages": [
                        HumanMessage(
                            content=_check_briefing(
                                state,
                                state.get("materials") or "",
                                state.get("facts") or "",
                            )
                        )
                    ]
                },
                config,
            )
        except Exception:
            # 备用也失败时默认通过审查，不阻塞写作流程
            return {"chapter_review": {"passed": True, "problems": ""}}
    return {"report": _last_reply(result.get("messages"))}


def save(state: ReaderState, config: RunnableConfig) -> dict:
    """收结论：判词在这儿解析。解析不出来按通过 —— 卡死整轮比放过一章糟。"""
    value = _parsed(state.get("report") or "")
    return {"chapter_review": _verdict(value), "chapter_conflicts": _conflicts(value)}


# 进出一行人话打印（agents/novel/utils/trace.py），只管调式，不动流程。
_reader_flow = StateGraph(ReaderState, input_schema=ReaderInput, output_schema=ReaderOutput)
_reader_flow.add_node("gather", traced("reader.gather")(gather))
_reader_flow.add_node("check", traced("reader.check")(check))
_reader_flow.add_node("save", traced("reader.save")(save))
_reader_flow.add_edge(START, "gather")
# gather 自己定去路（守卫拦下 / 正常核验），两条路都在图里。
_reader_flow.add_conditional_edges(
    "gather",
    _route_after_gather,
    {"check": "check", "done": END},
)
_reader_flow.add_edge("check", "save")
_reader_flow.add_edge("save", END)

# 不带 checkpointer：作为节点挂进父图时就用父图那个，子图每一步都落在同一个 thread 上。
reader = _reader_flow.compile(name="novel_reader")
