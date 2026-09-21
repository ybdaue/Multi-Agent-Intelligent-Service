"""审稿：查档 → 出题 → 核验 → 收结论，四步一条线。

先按 writer 报的台账把相关设定的原始档案取回来，拿档案出一份"必须核验"的问题清单，
再让审查 agent 对着正文答这份清单、顺带把六类硬伤过一遍，最后 save 解析成 chapter_review。
档案是事实底座、问题清单是注意力锚，两样都给；判词真假与回炉还是落库由图边定。
认「本轮新交稿」用 chapter_id 空不空（与 update 同口径）；子图对话不上交父图。
"""
from typing import Annotated, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agents.utils.models import parse_json_value
from ..state import ChapterMeta, ChapterReview, NovelMeta
from ..tools import fetchDB, read_skill_file
from ..utils.chapter_information import get_writer_context
from ..utils.ledger import fetch_ref_facts
from ..utils.model import MainModel
from ..utils.novel_information import render_protagonists
from ..utils.prompt import QUIZ_PROMPT, READER_PROMPT


class ReaderInput(TypedDict):
    """父图传进来的：小说设定、这一轮 writer 刚交的这一章（台账在里面）。"""

    novel: NovelMeta
    active_chapter: ChapterMeta


class ReaderOutput(TypedDict):
    """交回父图的：这一稿的审查结论。子图自己的材料与对话不上交。"""

    chapter_review: ChapterReview


class _Chat(TypedDict, total=False):
    """审查 agent 的对话。只用来装它自己的消息，材料与结论都在外面。"""

    messages: Annotated[list[AnyMessage], add_messages]


class ReaderState(TypedDict, total=False):
    novel: NovelMeta
    active_chapter: ChapterMeta
    materials: str                # gather 备好的设定与前文（不含正文与摘要，那两样在 check 里现摆）
    facts: str                    # 台账指向的那些行现在的档案
    questions: str                # quiz 出的问题清单
    report: str                   # check 交上来的原始判词
    chapter_review: ChapterReview


# 出题这一趟材料都在消息里，没有要查的东西，直接调模型就完。
_quizModel = MainModel(temperature=0.1, disable_streaming=True)

# 审查要稳定判断，temperature 比 writer 低；不挂 run_skill_script（只读文档）、
# 不挂"交结论"工具（判词就是模型的回复，收结论是 save 的事）。
# disable_streaming：输出是给父图判路用的，不是给前端的。
_reader_agent = create_agent(
    model=MainModel(temperature=0.1, disable_streaming=True),
    tools=[read_skill_file, fetchDB],
    system_prompt=READER_PROMPT,
    state_schema=_Chat,
)

_PASSED: ChapterReview = {"passed": True, "problems": ""}


def _last_reply(messages) -> str:
    """最后一条没有工具调用的助手回复 —— 审查结论就是它。"""
    for message in reversed(messages or []):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            content = message.content
            if isinstance(content, str) and content.strip():
                return content
    return ""


def _verdict(text: str) -> ChapterReview:
    """把模型那段 JSON 解析成 chapter_review。解析不出来、形状不对，一律当通过。"""
    try:
        value = parse_json_value(text)
    except ValueError:
        return dict(_PASSED)
    if not isinstance(value, dict) or not isinstance(value.get("passed"), bool):
        return dict(_PASSED)
    problems = value.get("problems")
    return {
        "passed": value["passed"],
        "problems": problems if isinstance(problems, str) else "",
    }


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


def _quiz_briefing(state: ReaderState, facts: str) -> str:
    """交给命题 agent 的：这一章是第几章、大概讲了什么，和要照着出题的档案。"""
    chapter = state.get("active_chapter") or {}
    order = chapter.get("chapter_order")
    title = chapter.get("chapter_title") or "未命名"
    lines = [f"请为第 {order} 章《{title}》出要核验的问题。"]

    summary = (chapter.get("chapter_summary") or "").strip()
    if summary:
        lines.append(f"本章摘要（只给你判断哪些档案该出题，正文不给）：\n\n{summary}")

    lines.append(f"本章涉及的设定在库里的档案：\n\n{facts}")
    return "\n\n".join(lines)


def _check_briefing(state: ReaderState, materials: str, facts: str, questions: str) -> str:
    """交给审查 agent 的：消息头、正文摘要、前文与设定、本章涉及设定的档案、问题清单、正文全文。

    档案与问题两样都给：档案是事实底座，问题是逼它一条条答的重点。
    """
    chapter = state.get("active_chapter") or {}
    order = chapter.get("chapter_order")
    title = chapter.get("chapter_title") or "未命名"
    lines = [f"请审第 {order} 章《{title}》。"]

    summary = (chapter.get("chapter_summary") or "").strip()
    if summary:
        lines.append(f"本章摘要：\n\n{summary}")

    lines.append(materials)

    if facts.strip():
        lines.append(
            "本章涉及的那些设定在库里的原始档案（库里现在的原样，不是正文里的说法）：\n\n"
            f"{facts.strip()}"
        )

    if questions.strip():
        lines.append(f"必须核验的问题（一条一条就着正文回答）：\n\n{questions.strip()}")

    lines.append(f"要审的这一章正文全文如下：\n\n{chapter.get('chapter_content') or ''}")
    lines.append(
        "上面档案没覆盖到的设定（本章没用到、正文里却冒出来的），要核对就用 fetchDB 按名字点查"
        "那一条，别整表拉。"
    )
    return "\n\n".join(lines)


async def gather(state: ReaderState, config: RunnableConfig) -> dict:
    """备材料：前文与设定从 get_writer_context 一次取回，台账指向的档案按 refId 从库里取。

    守卫也在这儿 —— 没新稿、拿不到书号就直接把结论写成「通过」，后面三步都不跑。
    """
    chapter = state.get("active_chapter") or {}
    # chapter_id 非空 = 这一章已落过库，state 里那份是上一轮的遗留，不是本轮交的稿。
    if not chapter.get("chapter_content") or chapter.get("chapter_id"):
        return {"chapter_review": dict(_PASSED)}

    novel_id = (config.get("configurable") or {}).get("novel_id")
    if not novel_id:
        # 拿不到书号就取不回前文和大纲，审不出名堂，放行让 update 去落库。
        return {"chapter_review": dict(_PASSED)}

    # 显式给序号，不靠"下一章"去推：改既有章节时这一章早就在库里，按下一章算会把要审的这章
    # 自己当成"上一章"。
    context = await get_writer_context(novel_id, chapter.get("chapter_order"))
    facts = await fetch_ref_facts(novel_id, chapter.get("chapter_refs"))
    return {"materials": _materials(state, context), "facts": facts}


def _route_after_gather(state: ReaderState) -> str:
    """gather 之后的去路：守卫拦下的（结论已经写好）收工，查得出档案的先出题，否则直接核验。"""
    if state.get("chapter_review"):
        return "done"
    return "quiz" if (state.get("facts") or "").strip() else "check"


def _no_questions(text: str) -> bool:
    """命题 agent 出不了题时的回话（提示词里约定的「无」），别当成一条问题甩给审查。"""
    return " ".join((text or "").split()).strip("。.！!：:") == "无"


async def quiz(state: ReaderState, config: RunnableConfig) -> dict:
    """对着查回来的档案出一份问题清单。"""
    reply = await _quizModel.ainvoke(
        [
            SystemMessage(content=QUIZ_PROMPT),
            HumanMessage(content=_quiz_briefing(state, state.get("facts") or "")),
        ]
    )
    questions = reply.content if isinstance(reply.content, str) else ""
    return {"questions": "" if _no_questions(questions) else questions.strip()}


async def check(state: ReaderState, config: RunnableConfig) -> dict:
    """答问题清单 + 过六类硬伤，交回原始判词。"""
    result = await _reader_agent.ainvoke(
        {
            "messages": [
                HumanMessage(
                    content=_check_briefing(
                        state,
                        state.get("materials") or "",
                        state.get("facts") or "",
                        state.get("questions") or "",
                    )
                )
            ]
        },
        config,
    )
    return {"report": _last_reply(result.get("messages"))}


def save(state: ReaderState, config: RunnableConfig) -> dict:
    """收结论：判词在这儿解析。解析不出来按通过 —— 卡死整轮比放过一章糟。"""
    return {"chapter_review": _verdict(state.get("report") or "")}


_reader_flow = StateGraph(ReaderState, input_schema=ReaderInput, output_schema=ReaderOutput)
_reader_flow.add_node("gather", gather)
_reader_flow.add_node("quiz", quiz)
_reader_flow.add_node("check", check)
_reader_flow.add_node("save", save)
_reader_flow.add_edge(START, "gather")
# gather 自己定去路（守卫拦下 / 没档案可查 / 正常出题），三条路都在图里。
_reader_flow.add_conditional_edges(
    "gather",
    _route_after_gather,
    {"quiz": "quiz", "check": "check", "done": END},
)
_reader_flow.add_edge("quiz", "check")
_reader_flow.add_edge("check", "save")
_reader_flow.add_edge("save", END)

# 不带 checkpointer：作为节点挂进父图时就用父图那个，子图每一步都落在同一个 thread 上。
reader = _reader_flow.compile(name="novel_reader")
