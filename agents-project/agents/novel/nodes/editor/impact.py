"""impact 节点：定位目标、取旧行、比差异、算范围。全是确定性的，一处语义判断都没有。"""
import uuid

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from ...utils.chapter_information import get_chapter, get_writer_context
from ..utils.impact import (
    EDIT_SPEC,
    collect_chapter_impact,
    collect_impact,
    editable_fields,
    find_target,
    render_change,
)
from .helpers import (
    _carried_impact,
    _fresh_draft,
    _is_chapter,
    _new_setting,
    _revise_brief,
    _setting_notes,
)
from .state import EditorState


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