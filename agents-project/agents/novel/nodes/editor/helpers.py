"""editor 子图的辅助方法与模型：计划/回炉判定、各类开场白拼装、新增设定的比对。"""
from ...utils.inspiration import render_inspirations
from ...utils.ledger import NEW_ENTITY_SPEC, TYPE_LABEL
from ...utils.model import BackupMainModel, MainModel
from ..utils.impact import collect_new_impact, column_label, field_notes, render_rows
from .state import EditorState

# 计划与判词都是小提示词 + JSON 出参，不需要工具循环，直接调模型。temperature 要稳定判断。
try:
    _editModel = MainModel(temperature=0.1, disable_streaming=True)
    _editModel_backup = BackupMainModel(temperature=0.1, disable_streaming=True)
    _revise_main = MainModel(temperature=0.7, disable_streaming=False)
except Exception:
    _editModel = None
    _editModel_backup = None
    _revise_main = None


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

    inspirations = render_inspirations(state.get("inspirations") or [])
    if inspirations:
        lines.append(f"用户这次给的素材：\n{inspirations}")

    lines.append(state.get("materials") or "")
    return "\n\n".join(line for line in lines if line)


def _context_brief(context: dict, order: int) -> str:
    """改这一章要对着看的：本章生效的大纲与世界规则、上一章全文、前文总结、设定目录。

    原稿不在这儿 —— 它单独摆在最后，免得模型把"要改的稿"和"参照物"看混。
    """
    lines = []

    main_outlines = [text for text in (context.get("main_outlines") or []) if text.strip()]
    if main_outlines:
        lines.append("本章生效的主线大纲：\n\n" + "\n\n".join(main_outlines))

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

    inspirations = render_inspirations(state.get("inspirations") or [])
    if inspirations:
        lines.append(f"用户这次给的素材：\n{inspirations}")

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


def _conflict_text(said: int, order: int) -> str:
    """他话里点名的章和他开着的那一章对不上时的回话。

    改正文就得改库里那一行，章号不能由模型认、也不能将就着改错那一章，所以不猜，请他先切过去。
    """
    return (
        f"你说的第 {said} 章，和你这会儿开着的第 {order} 章对不上。"
        f"我这边只认你正开着的那一章 —— 要改哪一章，先切到那一章，再跟我说。"
    )


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