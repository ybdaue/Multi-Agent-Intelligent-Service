"""reader 子图的辅助方法：模型/agent 构造、常量、判词解析与开场白拼装。"""
import re
import time
import uuid

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.messages import HumanMessage, SystemMessage

from agents.utils.models import ainvoke_with_fallback, parse_json_value

from ...state import ChapterConflict, ChapterReview
from ...tools import fetchDB
from ...utils.chapter_information import (
    BRANCH_MAX_CHAPTERS,
    CHAPTER_MAX_WORDS,
    CHAPTER_MIN_WORDS,
    count_chapter_words,
)
from ...utils.inspiration import render_chapter_inspirations, render_inspirations
from ...utils.model import BackupMainModel, MainModel
from ...utils.prompt import R_PACING_PROMPT
from .state import ReaderState, _Chat

# 审查要稳定判断，temperature 比 writer 低；都非流式（输出给父图判路，不是给前端的）。
# 这几步是"照材料下判词"，不需要长链条推理 —— 关掉 thinking（deepseek-v4.1-flash 默认开，
# 隐藏推理 token 按输出计费、也按输出计时，一个判词动不动几百 token 全是想出来的）。
# 主、备用都关：备用跟主用是同一个模型，留着 thinking 等于降级之后又慢回去。
# logic / style 不挂工具；pacing 挂 fetchDB（缺细节才点查），并用中间件硬限工具调用最多 2 次，
# 防它反复 ReAct 堆上下文、加延迟（超额调用被挡回，模型照已有信息把判词出完）。
def _review_model():
    return MainModel(
        temperature=0.1, disable_streaming=True, extra_body={"enable_thinking": False}
    )


def _review_backup():
    return BackupMainModel(
        temperature=0.1, disable_streaming=True, extra_body={"enable_thinking": False}
    )


try:
    _logic_main = _review_model()
    _logic_backup = _review_backup()
except Exception:
    _logic_main = None
    _logic_backup = None

try:
    _style_main = _review_model()
    _style_backup = _review_backup()
except Exception:
    _style_main = None
    _style_backup = None

try:
    _pacing_main = _review_model()
    _pacing_backup = _review_backup()
except Exception:
    _pacing_main = None
    _pacing_backup = None


def _pacing_agent_for(model) -> object:
    if model is None:
        return None
    try:
        return create_agent(
            model=model,
            tools=[fetchDB],
            middleware=[ToolCallLimitMiddleware(run_limit=2, exit_behavior="continue")],
            system_prompt=R_PACING_PROMPT,
            state_schema=_Chat,
        )
    except Exception:
        return None


_pacing_agent = _pacing_agent_for(_pacing_main)
_pacing_agent_backup = _pacing_agent_for(_pacing_backup)

_PASSED: ChapterReview = {"passed": True, "problems": ""}

# 判词里的问题可能是「1. …」「- …」「•…」这类列表行，拆条前把行首标记削掉。
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*•·]|\d+[.、)])\s*")
# 一章的问题行封顶：模型偶尔话痨，一长串会把受影响点面板刷屏。
_MAX_PROBLEM_ROWS = 20

# 冲突记的是"用户要的偏离了库里哪一类东西"。取值照 my-app/prisma/schema/novel.prisma 的
# ImpactTarget 抄，进库要按它查；认不出来的（模型写了中文、或写了 novel 这种不可能是冲突
# 对象的）一律不收 —— 收下来落库时枚举不过，整笔事务都会回滚。
_CONFLICT_TYPES = frozenset({
    "outline", "world_rule", "character", "faction", "item",
    "timeline", "chronicle", "foreshadowing",
})

# 三份判词合并时的问题来源标签。
_REPORT_LABELS = (
    ("logic_report", "连贯性"),
    ("pacing_report", "人物设定"),
    ("style_report", "文风"),
)


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


def _conflicts(value: dict) -> list[ChapterConflict]:
    """从 pacing 判词里取"用户要的跟库里对不上"的条目。

    只收认得出来的：类型得在白名单里，rule / want 得有一句能看的话。模型漏报、报歪都不耽误
    这一轮 —— 顶多少记一条台账，用户该看到的审查结论照样在。
    """
    rows = value.get("conflicts")
    if not isinstance(rows, list):
        return []
    out: list[ChapterConflict] = []
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


def _problem_rows(problems: str, order) -> list[dict]:
    """把审查判词里的问题逐条拆成影响台账行，由父图 update 落库。

    每一条问题各自一个 changeId：唯一键是 (changeId, targetType, targetId, reasonKind)，
    这几行 targetId 是空的（这一章还没落库、也没点出具体是哪条设定），同类问题若共用一个
    changeId 会在库里撞键、丢掉一条；各自成组反而更清楚。
    """
    rows: list[dict] = []
    for line in (problems or "").splitlines():
        text = _LIST_MARKER_RE.sub("", line).strip()
        if not text:
            continue
        rows.append({
            "changeId": uuid.uuid4().hex,
            "changeSummary": f"第 {order} 章审查问题",
            "sourceType": "chapter",
            "sourceId": "",              # 这一章还没落库，此刻还没有 id
            "oldValue": "",
            "newValue": "",
            "targetType": "chapter",
            "targetId": "",
            "targetChapter": order,
            "reasonKind": "review_issue",
            "reason": text,
            "severity": "must_fix",
            "detectedBy": "reader",
            "status": "pending",         # 待处理；用户重写审过后再翻成 fixed
            "resolution": "",
        })
        if len(rows) >= _MAX_PROBLEM_ROWS:
            break
    return rows


def _line_block(context: dict, order) -> str:
    """本章正处在的阶段线 / 支线，排成给审查员看的几行。

    支线带「已写几章 / 最多几章」这个硬数，供它判断"该收尾却还在铺新岔路"这种漂移。
    """
    blocks = []
    phases = context.get("phase_lines") or []
    if phases:
        rows = [f"- {p.get('content') or '（未命名）'}" for p in phases if isinstance(p, dict)]
        if rows:
            blocks.append("阶段线：\n" + "\n".join(rows))

    branches = context.get("branch_lines") or []
    if branches:
        rows = []
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            start = branch.get("start_order")
            elapsed = max(order - start, 0) if isinstance(start, int) else 0
            rows.append(
                f"- {branch.get('content') or '（未命名）'}"
                f"（已写 {elapsed} 章 / 最多 {BRANCH_MAX_CHAPTERS} 章）"
            )
        if rows:
            blocks.append("支线（临时小剧情）：\n" + "\n".join(rows))
    return "\n\n".join(blocks)


def _logic_input(state: ReaderState, context: dict) -> str:
    """R-Logic 的开场白：承接 + 连贯 + 漂移 + 世界规则，靠上一章全文与前文来核。"""
    chapter = state.get("active_chapter") or {}
    order = chapter.get("chapter_order")
    lines = [f"请审第 {order} 章的连贯性：这一章跟前面读起来连不连得上。"]

    prev_content = (context.get("prev_content") or "").strip()
    if prev_content:
        lines.append(f"上一章（第 {order - 1} 章）全文，对着它查承接和事件有没有跳：\n\n{prev_content}")
    else:
        lines.append("这是本书第一章，没有上一章可接，承接这一项跳过。")

    past = context.get("prev_past_summary") or {}
    past_text = (past.get("text") or "").strip() if isinstance(past, dict) else ""
    if past_text:
        lines.append(f"到第 {order - 1} 章为止的前文总结：\n\n{past_text}")

    main_outlines = [text for text in (context.get("main_outlines") or []) if text.strip()]
    if main_outlines:
        lines.append("本章生效的主线大纲，对着它查有没有跑偏：\n\n" + "\n\n".join(main_outlines))
    else:
        lines.append("库里还没有本章适用的大纲，漂移只看有没有脱离前文。")

    line_block = _line_block(context, order)
    if line_block:
        lines.append("本章正处在的阶段线 / 支线：\n\n" + line_block)
    else:
        lines.append("当前没有生效的阶段线 / 支线。")

    world_rules = context.get("world_rules") or []
    if world_rules:
        rules = "\n".join(f"- {r['name']}：{r['rule']}" for r in world_rules)
        lines.append(f"本章生效的世界规则、力量体系，对着它查有没有写崩：\n{rules}")
    else:
        lines.append("库里还没有本章适用的世界规则，这一项跳过。")

    lines.append(f"要审的这一章正文全文如下：\n\n{chapter.get('chapter_content') or ''}")
    return "\n\n".join(lines)


def _pacing_input(state: ReaderState, context: dict, facts: str) -> str:
    """R-Pacing 的开场白：人物与设定，靠档案与目录来核，缺细节才点查。"""
    chapter = state.get("active_chapter") or {}
    order = chapter.get("chapter_order")
    lines = [f"请审第 {order} 章的人物与设定：有没有 OOC、有没有把库里已有的设定另起名字重造。"]

    said = (state.get("user_message") or "").strip()
    if said:
        lines.append(f"用户对这一章的要求（他明确要的写法，可能跟下面库里的设定对不上）：\n\n{said}")

    prev_summary = (context.get("prev_summary") or "").strip()
    if prev_summary:
        lines.append(f"上一章（第 {order - 1} 章）的精简：\n\n{prev_summary}")

    catalog = (context.get("catalog") or "").strip()
    if catalog:
        lines.append("库里已有设定的目录（每行是「id 名字」，前面那串 id 不用管）：\n\n" + catalog)
    else:
        lines.append("库里还没有任何设定，目录是空的。")

    if facts.strip():
        lines.append(
            "本章涉及的那些设定在库里的原始档案（库里现在的原样，不是正文里的说法）：\n\n"
            + facts.strip()
        )

    lines.append(f"要审的这一章正文全文如下：\n\n{chapter.get('chapter_content') or ''}")
    lines.append(
        "照手上的材料下判词；只有本章突然用到某一条、而档案与目录都没给到它的细节时，才用 fetchDB "
        "点查那一条，最多一次。正文里出现的名字若不在目录里，就当它是这一章新造的，不必去找。"
    )
    return "\n\n".join(lines)


def _style_input(state: ReaderState, context: dict) -> str:
    """R-Style 的开场白：文风与用料，靠风格设定与用户素材来核。"""
    chapter = state.get("active_chapter") or {}
    order = chapter.get("chapter_order")
    novel = state.get("novel") or {}
    lines = [f"请审第 {order} 章的文风。"]

    style = novel.get("novel_style") or ""
    tropes = novel.get("novel_tropes") or ""
    if style or tropes:
        lines.append(f"这本书的小说风格：{style or '未填'}；小说套路：{tropes or '未填'}。")

    materials = []
    said = (state.get("user_message") or "").strip()
    if said:
        materials.append(f"用户对这一章的要求：\n\n{said}")
    # 有本章选定的灵感就用它（带写作指引，逐条核有没有落到正文）；没有才退回本轮用户给的素材。
    chosen = state.get("chapter_inspirations") or []
    if chosen:
        materials.append(f"本章要用的灵感（照每条的写作指引核正文用没用上）：\n{render_chapter_inspirations(chosen)}")
    else:
        inspirations = render_inspirations(state.get("inspirations") or [])
        if inspirations:
            materials.append(f"用户这次给的素材：\n{inspirations}")
    if materials:
        lines.append("用户这一轮给的素材与要求，对着它查正文用没用上、贴不贴：\n\n" + "\n\n".join(materials))
    else:
        lines.append("用户这一轮没给素材，贴合素材这一项跳过，只看风格与文笔。")

    lines.append(f"要审的这一章正文全文如下：\n\n{chapter.get('chapter_content') or ''}")
    return "\n\n".join(lines)


async def _plain_review(primary, backup, system: str, content: str, label: str) -> str:
    """无工具审查员：一次非流式调用，交回原始判词。失败交空串（save 当通过）。"""
    if primary is None:
        return ""
    started = time.monotonic()
    try:
        reply = await ainvoke_with_fallback(
            primary, backup, [SystemMessage(content=system), HumanMessage(content=content)]
        )
    except Exception:
        print(f"[reader] {label} 审查失败（耗时 {time.monotonic() - started:.1f}s），当通过")
        return ""
    print(f"[reader] {label} 审查完成，耗时 {time.monotonic() - started:.1f}s（输入 {len(content)} 字）")
    return reply.content if isinstance(reply.content, str) else ""


def _word_problem(chapter: dict) -> str:
    """字数校验：由代码确定性判定（不靠模型，免得它数漏）。

    正文落在 CHAPTER_MIN_WORDS-CHAPTER_MAX_WORDS 之外就回一句能照着改的话。
    """
    words = count_chapter_words(chapter.get("chapter_content") or "")
    if CHAPTER_MIN_WORDS <= words <= CHAPTER_MAX_WORDS:
        return ""
    if words < CHAPTER_MIN_WORDS:
        return (
            f"【字数】这一章正文才 {words} 字，不到 {CHAPTER_MIN_WORDS}。照 references/content-expansion.md "
            f"把情节写开、场景与对话补足，仍是这一章、不要另起一章。"
        )
    return (
        f"【字数】这一章正文 {words} 字，超过 {CHAPTER_MAX_WORDS}。番茄单章太长会掉完读率，"
        f"精简到 {CHAPTER_MIN_WORDS}-{CHAPTER_MAX_WORDS} 之间。"
    )


def _merge_reports(state: ReaderState) -> ChapterReview:
    """三份判词 + 字数校验合成一份结论：三者皆过且字数合格才算过。

    problems 带上来源标签（【连贯性】/【人物设定】/【文风】/【字数】），用户与回炉都看得清是哪来的。
    某一路失败（没交判词）按通过算 —— 卡死整轮比放过一章糟。
    """
    problems: list[str] = []
    passed = True
    for key, label in _REPORT_LABELS:
        verdict = _verdict(_parsed(state.get(key) or ""))
        if verdict["passed"]:
            continue
        passed = False
        text = (verdict.get("problems") or "").strip()
        problems.append(f"【{label}】{text}" if text else f"【{label}】（审出问题但没写清具体问题）")

    word = _word_problem(state.get("active_chapter") or {})
    if word:
        passed = False
        problems.append(word)

    return {"passed": passed, "problems": "\n".join(problems)}