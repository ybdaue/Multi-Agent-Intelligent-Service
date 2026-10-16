"""writer 子图的辅助方法与模型：提示词拼装、任务卡渲染 / 解析、材料与预算拼装。"""
import uuid

from agents.utils.models import parse_json_value

from ...utils.chapter_information import (
    BRANCH_MAX_CHAPTERS,
    CHAPTER_MAX_WORDS,
    CHAPTER_MIN_WORDS,
    PHASE_MAX_CHAPTERS,
)
from ...utils.inspiration import CATEGORY_LABEL, render_chapter_inspirations, render_inspirations
from ...utils.ledger import normalize_lines
from ...utils.model import MainModel
from ...utils.novel_information import render_protagonists
from ...utils.prompt import WRITER_PROMPT
from ...utils.skills import skill_path
from ...utils.trace import LlmWatch
from .state import WriterState

# 写手模型：开着流式，这一路的 token 要逐字发给前端当打字机。
# LlmWatch 挂回调只为打印：这次到底调没调模型、生成用了多久、要没要调工具。回调挂在模型
# 实例上，不动图结构，流式照旧。
try:
    _writer_main = MainModel(
        temperature=0.7, disable_streaming=False, callbacks=[LlmWatch("writer.write")]
    )
except Exception:
    _writer_main = None

# planner 出任务卡：判主线这一步、定禁止项，要稳不要发挥，温度压低、不给前端流。
try:
    _planner_main = MainModel(temperature=0.2, disable_streaming=True)
except Exception:
    _planner_main = None


def _writer_system_prompt() -> str:
    """写手的系统提示：WRITER_PROMPT 再附上 writerSkill/SKILL.md 全文。

    SKILL.md 是死文档 —— 写任何一章读的都是同一份。预读进来，写手就不必再花一轮 LLM 往返
    去调 read_skill_file 读它（references 那几份仍按需再读）。读不到就退回原提示，行为不变。
    """
    try:
        doc = skill_path("writerSkill", "SKILL.md").read_text(encoding="utf-8")
    except Exception:
        return WRITER_PROMPT
    return (
        f"{WRITER_PROMPT}\n\n"
        "# writerSkill / SKILL.md（全文，系统已替你读好，不必再调工具读它）\n\n"
        f"{doc}"
    )


def _retry_note(state: WriterState, order: int, problems: str, feedback: str = "") -> str:
    """上一稿被打回时的抬头：原稿全文 + 审查意见 / 用户要求，让模型在原稿上改。"""
    chapter = state.get("active_chapter") or {}
    lines = [f"【回炉重写】第 {order} 章的上一稿要再改一版。"]
    if problems:
        lines.append(f"审查意见：\n\n{problems}")
    # 审查通过、用户却要再改时 problems 是空的，只有这一块 —— 少了它模型就无从改起。
    if feedback:
        lines.append(f"用户看过这一稿之后又说：\n\n{feedback}")

    draft = (chapter.get("chapter_content") or "").strip()
    if draft:
        lines.append(
            "上一稿全文如下。按上面的意见改那几处，其余内容保留，不要整章从头重写，"
            f"也不要借机改设定：\n\n{draft}"
        )
    lines.append(
        f"改完还是第 {order} 章，整章重发一次；字数仍要 {CHAPTER_MIN_WORDS}-{CHAPTER_MAX_WORDS}。"
        f"开头照旧独占一行写「【正文】」，末尾的台账照这份重发一遍"
        f"（改完用了什么、新造了什么，可能跟上一稿不一样了）。"
    )
    return "\n\n".join(lines)


_ACTION_LABEL = {"continue": "接着写", "close": "收尾", "open": "新开"}


def _render_card(card: dict) -> str:
    """任务卡 dict → 给写手看的几行。空格不写；解不出 JSON 时退回 planner 的原文。"""
    if not isinstance(card, dict) or not card:
        return "（这一轮没撇出任务卡，就照主线大纲和材料往下写。）"
    lines = []
    plot = (card.get("plot") or "").strip()
    if plot:
        lines.append(f"- 主线这一步：{plot}")
    for key, label in (("phase", "阶段线"), ("branch", "支线（本阶段下）")):
        block = card.get(key)
        if not isinstance(block, dict):
            continue
        action = str(block.get("action") or "").strip()
        content = (block.get("content") or "").strip()
        if not action and not content:
            continue
        shown = _ACTION_LABEL.get(action, action)
        lines.append(f"- {label}：{shown}{('：' + content) if content else ''}")
    settings = card.get("settings")
    if isinstance(settings, list):
        rows = [
            f"  - {s.get('name')}（{s.get('refType') or ''}）：{(s.get('info') or '').strip()}"
            for s in settings
            if isinstance(s, dict) and (s.get("name") or "").strip()
        ]
        if rows:
            lines.append("- 本章要用的已有设定（照这些保持一致）：\n" + "\n".join(rows))
    foreshadow = card.get("foreshadowing")
    if isinstance(foreshadow, list):
        rows = [
            f"  - {f.get('id')}：{(f.get('how') or '').strip()}"
            for f in foreshadow
            if isinstance(f, dict) and str(f.get("id") or "").strip()
        ]
        if rows:
            lines.append(
                "- 本章要收尾的伏笔（照它收；收完照旧在台账 refs 里报它，并把它报进台账的 resolved）：\n"
                + "\n".join(rows)
            )
    forbidden = (card.get("forbidden") or "").strip()
    if forbidden:
        lines.append(f"- 这一章不要写：{forbidden}")
    carry = (card.get("carry") or "").strip()
    if carry:
        lines.append(f"- 必须接住：{carry}")
    if not lines:
        note = (card.get("note") or "").strip()
        return note or "（这一轮没撇出任务卡，就照主线大纲和材料往下写。）"
    return "\n".join(lines)


def _parse_card(text: str) -> dict:
    """planner 那段卡 JSON → dict；解不出来就把原文放进 note，交给渲染兜底。"""
    text = (text or "").strip()
    if not text:
        return {}
    try:
        value = parse_json_value(text)
    except (ValueError, TypeError):
        value = None
    return value if isinstance(value, dict) else {"note": text}


def _card_lines(card: dict, context: dict) -> list[dict]:
    """任务卡的 phase / branch → 这一章的阶段线 / 支线，交给 collect 落库（open/continue/close）。

    写手不再自己报 lines —— 那是 planner 照预算硬数定的事，写手只管照卡写。normalize_lines
    会把开线没内容、沿用/收尾没 id 的整条丢掉。

    包含关系（主线 ⊃ 阶段线 ⊃ 支线）由**代码**挂，不由模型填：新开阶段线挂本章主线下
    （main_line_id）；新开支线挂在当前生效阶段线下 —— 本章若同时新开了阶段线就挂它（用预生成的
    id 让同一章的支线指得到它），否则挂当前那条阶段线。id 也在这儿预生成，父子同章才连得上。
    """
    if not isinstance(card, dict):
        return []
    raw = []
    for level in ("phase", "branch"):
        block = card.get(level)
        if not isinstance(block, dict):
            continue
        action = str(block.get("action") or "").strip()
        if action not in ("open", "continue", "close"):
            continue
        raw.append({
            "level": level,
            "action": action,
            "id": str(block.get("id") or "").strip(),
            "content": str(block.get("content") or "").strip(),
        })

    main_line_id = str(context.get("main_line_id") or "")
    current_phase_id = str((_current_line(context.get("phase_lines") or []) or {}).get("id") or "")

    lines: list[dict] = []
    open_phase_id = ""            # 本章新开的阶段线 id，供同章的支线挂父
    for line in normalize_lines(raw):
        if line["action"] == "open":
            new_id = uuid.uuid4().hex
            if line["level"] == "phase":
                open_phase_id = new_id
                parent = main_line_id
            else:
                parent = open_phase_id or current_phase_id
            lines.append({**line, "id": new_id, "parentId": parent})
        else:
            # continue / close 不动父：父在开线那章就挂好了。
            lines.append({**line, "parentId": ""})
    return lines


def _current_line(lines: list) -> dict | None:
    """生效中的线里挑"当前这条"：起始章号最大的那条（最近开的那条）。阶段线 / 支线共用。"""
    best = None
    best_key = -1
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        start = line.get("start_order")
        key = start if isinstance(start, int) else -1
        if best is None or key > best_key:
            best, best_key = line, key
    return best


def _elapsed(line: dict, order: int) -> int:
    """这条线从起始章写到第 order 章，之前已经写了几年（起始章那章就是它的第 1 章）。"""
    start = line.get("start_order")
    return max(order - start, 0) if isinstance(start, int) else 0


def _constraint_block(context: dict, order: int) -> str:
    """阶段线 / 支线的章节预算：由代码算死的硬数，拼进 planner / 写手提示词，保证一定出现、
    不受模型拿捏。

    阶段线（主线切出来的大阶段）从 start_order 那一章起头，写到第 order 章就是它的第
    (order - start_order + 1) 章；到 PHASE_MAX_CHAPTERS 就到点，必须收尾 —— **一本小说必须
    一直有阶段线在写**，所以没有阶段线时这一章必须 open 一条。支线同构，用 BRANCH_MAX_CHAPTERS，
    挂在当前阶段线下。收尾与开新分两章：到点这一章 close，下一章没有生效线了再 open。
    """
    lines = [
        "【阶段线 / 支线章节预算】系统算好的硬数，不许自己改：",
        f"- 这本书已有 {max(order - 1, 0)} 章，这一章是第 {order} 章。",
    ]

    phase = _current_line(context.get("phase_lines") or [])
    if phase is None:
        lines.append(
            "- 当前没有阶段线在写。阶段线是主线切出来的大阶段，**一本小说必须一直有阶段线**："
            "这一章必须 open 一条阶段线（系统会把它挂在主线下）。"
        )
    else:
        elapsed = _elapsed(phase, order)
        this_no = elapsed + 1
        lines.append(f"- 当前阶段线：{phase.get('content') or '（未命名）'}")
        lines.append(f"  - 它已经写了 {elapsed} 章，最多写 {PHASE_MAX_CHAPTERS} 章。")
        if this_no >= PHASE_MAX_CHAPTERS:
            lines.append(
                f"  - 这一章是它的第 {this_no} 章 → 到点了：**必须在这一章把它 close 收尾**"
                f"（收束回主线）；下一条阶段线下一章再 open。本章别再开新支线。"
            )
        else:
            lines.append(
                f"  - 这一章是它的第 {this_no} 章，还剩 {PHASE_MAX_CHAPTERS - this_no} 章 → 继续推进，"
                f"别另开新阶段。"
            )

    branch = _current_line(context.get("branch_lines") or [])
    if branch is None:
        lines.append(
            f"- 当前没有支线在写。要开一条临时小剧情就在**当前阶段线之下** open，它最多写 "
            f"{BRANCH_MAX_CHAPTERS} 章。"
        )
        return "\n".join(lines)

    elapsed = _elapsed(branch, order)
    this_no = elapsed + 1
    lines.append(f"- 当前支线：{branch.get('content') or '（未命名）'}")
    lines.append(f"  - 它已经写了 {elapsed} 章，最多写 {BRANCH_MAX_CHAPTERS} 章。")
    if this_no >= BRANCH_MAX_CHAPTERS:
        lines.append(
            f"  - 这一章是它的第 {this_no} 章 → 到点了：**必须在这一章把它 close 收尾、收束回主线**"
            f"（下一条支线下一章再 open）。"
        )
    else:
        lines.append(
            f"  - 这一章是它的第 {this_no} 章，还剩 {BRANCH_MAX_CHAPTERS - this_no} 章 → 继续推进，"
            f"但别另开新岔路。"
        )
    return "\n".join(lines)


# 未收尾伏笔块给 planner 的篇幅上限：悬着的伏笔多了先摆先埋的几条，多的截掉。
MAX_FORESHADOW_CHARS = 4_000


def _foreshadowing_block(rows) -> str:
    """未收尾的伏笔清单：代码从库里取好、拼成一段，**保证一定出现在 planner 输入里**
    （比照 _constraint_block 的做法）。planner 照每条的「打算的收尾场景」判本章该不该收，
    这些信息必须摆到它面前，不能指望它自己去查库。

    一条都没有也要写明"没有"，好让 planner 确知"已经读过、确实没有"。
    """
    lines = ["【未收尾的伏笔】系统从库里取好的，一条都不许漏看："]
    items = [r for r in (rows or []) if isinstance(r, dict) and r.get("id")]
    if not items:
        lines.append("- 没有未收尾的伏笔。")
        return "\n".join(lines)
    for row in items:
        order = row.get("planted_order")
        planted = f"埋在 第 {order} 章" if isinstance(order, int) else "埋设章节已删"
        scenario = str(row.get("resolveScenario") or "").strip()
        desc = " ".join(str(row.get("description") or "").split())
        tail = f"；打算的收尾场景：{scenario}" if scenario else "；（埋的时候没写收尾场景）"
        lines.append(f"- {row['id']} {desc}（{planted}{tail}）")
    text = "\n".join(lines)
    if len(text) > MAX_FORESHADOW_CHARS:
        text = text[:MAX_FORESHADOW_CHARS] + "…（未收尾伏笔太多，只列到这里）"
    return text


# 人物关系块给 planner / 写手的篇幅上限：相关的人多了先摆先建的几条，多的截掉。
MAX_RELATION_CHARS = 4_000


def _relation_block(rows) -> str:
    """本章相关人物当前的「人物关系」：代码从库里取好、拼成一段，**保证一定出现在
    planner 输入与写手开场里**（比照 _foreshadowing_block）。写的时候照它保持关系一致
    （谁跟谁是什么关系），不靠模型自己去查库、也不靠 planner 转述。

    一条都没有也要写明「没有」，好让它确知「已经读过、确实没有」。
    """
    lines = ["【本章涉及的人物关系】库里记着的当前关系，写的时候照它保持一致（谁跟谁是什么关系）："]
    items = [r for r in (rows or []) if isinstance(r, dict) and r.get("id")]
    if not items:
        lines.append("- 本章相关的人物，库里还没有记关系。")
        return "\n".join(lines)
    for row in items:
        pair = f"{row.get('fromName') or '？'}→{row.get('toName') or '？'}"
        kind = str(row.get("relationType") or "").strip()
        strength = row.get("strength")
        mark = f"（强度 {strength}）" if isinstance(strength, int) else ""
        desc = str(row.get("description") or "").strip()
        tail = f"：{desc}" if desc else ""
        lines.append(f"- {row['id']} {pair} {kind}{mark}{tail}")
    text = "\n".join(lines)
    if len(text) > MAX_RELATION_CHARS:
        text = text[:MAX_RELATION_CHARS] + "…（相关关系太多，只列到这里）"
    return text


def _lines_catalog(context: dict, order: int) -> str:
    """生效中的阶段线 / 支线目录：接着写照抄 id 报 continue，收尾报 close，换新报 open。

    按「主线 ⊃ 阶段线 ⊃ 支线」的层级排：阶段线在下，支线标出它挂在哪条阶段线下。主线内容另在
    `_materials` 的「主线大纲」一块给，这里不重复；空则空串。
    """
    blocks = []
    phases = context.get("phase_lines") or []
    if phases:
        rows = []
        for phase in phases:
            if not isinstance(phase, dict):
                continue
            elapsed = _elapsed(phase, order)
            rows.append(
                f"- {phase.get('id')} {phase.get('content') or ''}"
                f"（已写 {elapsed} 章 / 最多 {PHASE_MAX_CHAPTERS} 章）"
            )
        if rows:
            blocks.append("现有阶段线（phase，挂在主线下）：\n" + "\n".join(rows))

    branches = context.get("branch_lines") or []
    if branches:
        rows = []
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            elapsed = _elapsed(branch, order)
            parent = branch.get("parent_id") or ""
            rows.append(
                f"- {branch.get('id')} {branch.get('content') or ''}"
                f"（挂在阶段线 {parent or '？'} 下；已写 {elapsed} 章 / 最多 {BRANCH_MAX_CHAPTERS} 章）"
            )
        if rows:
            blocks.append("现有支线（branch，挂在阶段线下）：\n" + "\n".join(rows))
    return "\n\n".join(blocks)


def _materials(state: WriterState, context: dict) -> str:
    """planner 与写手共用的材料：小说 meta、主角、主线大纲、阶段线/支线、世界规则、
    近章摘要（上一章精简 / 上上一章精简 / 前文总结）、设定目录。**不含上一章全文**（那是写手专属）。"""
    novel = state.get("novel") or {}
    order = context["chapter_order"]
    lines = [
        f"《{novel.get('novel_title') or '未命名'}》；"
        f"小说套路：{novel.get('novel_tropes') or '未填'}；"
        f"小说风格：{novel.get('novel_style') or '未填'}。"
    ]

    protagonists = render_protagonists(novel)
    if protagonists:
        lines.append(f"主角：\n{protagonists}")

    main_outlines = [text for text in (context.get("main_outlines") or []) if text.strip()]
    if main_outlines:
        lines.append("主线大纲（整本的主心骨，一直是它）：\n\n" + "\n\n".join(main_outlines))
    else:
        lines.append("库里还没有主线大纲，就按前文和你对这本书的了解往下写。")

    lines_catalog = _lines_catalog(context, order)
    if lines_catalog:
        lines.append("正在写 / 生效中的阶段线、支线（主线 ⊃ 阶段线 ⊃ 支线）：\n\n" + lines_catalog)

    world_rules = context.get("world_rules") or []
    if world_rules:
        rules = "\n".join(f"- {r['name']}：{r['rule']}" for r in world_rules)
        lines.append(f"本章生效的世界规则、力量体系，别写崩：\n{rules}")
    else:
        lines.append("库里还没有本章适用的世界规则。")

    prev_summary = (context.get("prev_summary") or "").strip()
    if prev_summary:
        lines.append(f"上一章（第 {order - 1} 章）的精简，接着它写：\n\n{prev_summary}")
    else:
        lines.append("这是本书第一章，没有上一章可接，自己开篇。")

    prev_prev_summary = (context.get("prev_prev_summary") or "").strip()
    if prev_prev_summary:
        lines.append(f"上上一章（第 {order - 2} 章）的精简：\n\n{prev_prev_summary}")

    past_summary = context.get("prev_past_summary") or {}
    past_text = (past_summary.get("text") or "").strip() if isinstance(past_summary, dict) else ""
    if past_text:
        lines.append(f"到第 {order - 1} 章为止的前文总结：\n\n{past_text}")

    catalog = (context.get("catalog") or "").strip()
    if catalog:
        lines.append(
            "库里已有的设定目录（每行是「id 名字」，id 是后面台账要用的编号）：\n\n"
            f"{catalog}\n\n"
            "这一章用到或提到目录里的哪一条，就在台账的 refs 里报它的 id。"
        )
    else:
        lines.append(
            "库里还没有任何设定，目录是空的。这一章用到的都是新造的，照「交稿」一节报进 new。"
        )
    return "\n\n".join(lines)


def _menu_item_line(item: dict, tag: str = "") -> str:
    """菜单里一条灵感压成一行：id（planner 挑人时报它）、标题、类型、场景 / 写作指引。"""
    title = (item.get("title") or item.get("name") or "未命名").strip()
    cats = "、".join(CATEGORY_LABEL.get(c, c) for c in (item.get("category") or [])) or "未分类"
    marks = [m for m in (tag, "已用" if item.get("used") else "未用") if m]
    tail = ""
    scenario = (item.get("scenario") or "").strip()
    if scenario:
        tail += f"；场景：{scenario}"
    digest = (item.get("digest") or "").strip()
    if digest:
        tail += f"；指引：{digest}"
    return f"- {item.get('id')} 《{title}》〔{cats}〕（{'／'.join(marks)}）{tail}"


def _inspiration_menu_block(menu: dict) -> str:
    """灵感菜单渲染给 planner：必用的摆上面（系统指定，必须用），可选的摆下面（按需挑）。

    每条带 id —— planner 从可选里挑了，就在任务卡的 inspirations 里报这个 id 与本章怎么用；
    必用的不用报，代码会直接带进去。
    """
    forced = [i for i in (menu.get("forced") or []) if isinstance(i, dict)]
    optional = [i for i in (menu.get("optional") or []) if isinstance(i, dict)]
    if not forced and not optional:
        return ""
    blocks = ["【灵感菜单】这一章可以从这些灵感里取材："]
    if forced:
        blocks.append(
            "必用（系统指定，这一章必须用进去，不用你在任务卡里报）：\n"
            + "\n".join(_menu_item_line(i, tag="必须用") for i in forced)
        )
    if optional:
        blocks.append(
            "可选用（按需挑本章用得上的，挑中的在任务卡的 inspirations 里报它的 id 与用法）：\n"
            + "\n".join(_menu_item_line(i) for i in optional)
        )
    return "\n\n".join(blocks)


def _optional_inspirations_block(menu: dict) -> str:
    """给写手的「还能补选」清单：可选用的灵感（必用的已在【本章要用的灵感】里给过，不重复）。

    写手若在正文里额外用上了这里的一条，就在台账 refs 里报它的 id —— 台账记「这一章用了哪几条」。
    """
    optional = [i for i in (menu.get("optional") or []) if isinstance(i, dict)]
    if not optional:
        return ""
    return (
        "【还能补选的灵感】库里可选用的还有这些；本章若还用到其中哪条，"
        "在台账 refs 里报它的 id（用了才报，没用别报）：\n"
        + "\n".join(_menu_item_line(i) for i in optional)
    )


def _chosen_inspirations(state: WriterState, card: dict, menu: dict) -> list[dict]:
    """本章最终要用的灵感（**代码合并**，不由模型拿捏）：本轮用户点名的 ∪ 必用 ∪ planner 从可选里挑的。

    用户这一轮在对话框点名的（state.inspirations）这一章必须用；forced（必用 / 风格）每章必带；
    planner 从可选里挑的带上它给的 how。按 id 去重，返回完整行（带 how 供渲染）。
    """
    forced = menu.get("forced") or []
    optional = {
        str(i.get("id")): i
        for i in (menu.get("optional") or [])
        if isinstance(i, dict) and i.get("id")
    }
    picks = card.get("inspirations") if isinstance(card, dict) else None
    how: dict[str, str] = {}
    if isinstance(picks, list):
        for pick in picks:
            if isinstance(pick, dict) and str(pick.get("id") or "").strip():
                how[str(pick["id"])] = str(pick.get("how") or "").strip()

    chosen: list[dict] = []
    seen: set[str] = set()
    for item in list(state.get("inspirations") or []) + list(forced):
        if not isinstance(item, dict):
            continue
        key = str(item.get("id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        chosen.append({**item, "how": ""})
    for pid, use in how.items():
        item = optional.get(pid)
        if item is None or pid in seen:
            continue
        seen.add(pid)
        chosen.append({**item, "how": use})
    return chosen


def _planner_input(state: WriterState) -> str:
    """交给 planner 的：本轮用户要求 + 素材 + 共用材料 + 阶段线/支线预算 + 上一章设定档案（**不含上一章全文**）。"""
    bundle = state.get("bundle") or {}
    order = bundle.get("order")
    lines = [f"请为第 {order} 章出一张任务卡。"]
    said = (state.get("user_message") or "").strip()
    if said:
        lines.append(f"用户这一轮对这一章的要求：\n\n{said}")
    picked = render_inspirations(state.get("inspirations") or [])
    if picked:
        lines.append(f"用户这一轮点名要用进这一章的灵感（必须用，别漏）：\n{picked}")
    menu_block = _inspiration_menu_block(bundle.get("inspirations") or {})
    if menu_block:
        lines.append(menu_block)
    materials = bundle.get("materials") or ""
    if materials:
        lines.append(materials)
    budget = bundle.get("budget") or ""
    if budget:
        lines.append(budget)
    # 未收尾的伏笔由代码取好、无条件摆出来（空也说"没有"）：planner 必须读到它们才判得出本章该收哪些。
    lines.append(_foreshadowing_block(bundle.get("foreshadowing")))
    # 相关人物当前的关系也由代码取好、无条件摆出来 —— planner 照它挑本章要用的人 / 保持戏份一致。
    lines.append(_relation_block(bundle.get("relations")))
    facts = (bundle.get("prev_facts") or "").strip()
    if facts:
        lines.append("上一章用到的那些设定，在库里的原始档案：\n\n" + facts)
    return "\n\n".join(lines)


def _briefing(state: WriterState, card: dict, chosen: list[dict] | None = None) -> str:
    """交给写手的开场：任务卡 + 支线预算摆在最前，材料（含上一章全文与设定档案）在后。"""
    bundle = state.get("bundle") or {}
    order = bundle.get("order")
    review = state.get("chapter_review") or {}
    problems = "" if review.get("passed", True) else (review.get("problems") or "").strip()
    feedback = (state.get("edit_feedback") or "").strip()

    lines = [f"请写第 {order} 章。" + ("（回炉重写）" if (problems or feedback) else "")]
    if problems or feedback:
        lines.append(_retry_note(state, order, problems, feedback))
    # 用户这一轮自己说的那句要原样摆进来：「这一章只写什么、不写什么」只说在这句话里。
    # 回炉时也照摆，但说法得换：回炉意味着读者看过这一稿之后点了"按库里改"（或审查没过），
    # 那是他后来改的口 —— 再让"以他原话为准"压在上面，两边就一直对着干、来回空转。
    said = (state.get("user_message") or "").strip()
    if said:
        if problems or feedback:
            lines.append(f"用户当初对这一章的要求（按上面的回炉意见来，别照它顶）：\n\n{said}")
        else:
            lines.append(f"用户对这一章的要求（照它写，它跟大纲冲突时以它为准）：\n\n{said}")

    chosen = chosen if chosen is not None else (state.get("chapter_inspirations") or [])
    if chosen:
        lines.append(
            "【本章要用的灵感】照每条的写作指引用进去，别漏：\n"
            + render_chapter_inspirations(chosen)
        )

    # 可选用的那份也摆出来，写手才补选得动（用了在台账 refs 里报 id）。
    optionals = _optional_inspirations_block(bundle.get("inspirations") or {})
    if optionals:
        lines.append(optionals)

    lines.append("【本章任务卡】照它写，别跑偏：\n" + _render_card(card))
    budget = bundle.get("budget") or ""
    if budget:
        lines.append(budget)
    materials = bundle.get("materials") or ""
    if materials:
        lines.append(materials)

    prev_content = (bundle.get("prev_content") or "").strip()
    if prev_content:
        lines.append(f"上一章（第 {order - 1} 章）全文，接着它写：\n\n{prev_content}")

    # 本章相关人物当前的关系也照摆（planner 已照卡里的人物并集补查过）：写的时候照它保持一致。
    lines.append(_relation_block(bundle.get("relations")))

    facts = (bundle.get("prev_facts") or "").strip()
    if facts:
        lines.append(
            "上一章用到的那些设定，在库里的原始档案（库里现在的原样，照它保持一致）：\n\n" + facts
        )
    return "\n\n".join(lines)