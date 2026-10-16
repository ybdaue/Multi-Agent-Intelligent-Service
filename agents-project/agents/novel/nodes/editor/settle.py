"""settle 节点：设定这一路 —— 拿这一类现有的全部内容定夺并进哪一条、还是新增。"""
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from agents.utils.models import ainvoke_with_fallback, parse_json_value

from ..utils.impact import editable_fields, exists_by_key, list_entries, render_entries
from ...utils.ledger import NEW_ENTITY_SPEC, TYPE_LABEL, normalize_new
from ...utils.prompt import SETTLE_PROMPT
from .helpers import _editModel, _editModel_backup, _settle_brief
from .state import EditorState


async def settle(state: EditorState, config: RunnableConfig) -> dict:
    """设定这一路：拿这一类现有的全部内容跟用户要补的东西比一遍，定夺并进哪一条、还是新增。

    全图唯一产出 fields 的地方，也是唯一决定 update 还是 create 的地方。清单里的内容看得到
    才谈得上"冲突了才覆盖、且只覆盖冲突那几列"—— plan 拿着目录挑一条，挑的就是要被盖掉的那条。
    """
    novel_id = (config.get("configurable") or {}).get("novel_id")
    plan = state.get("plan") or {}
    target_type = str(plan.get("targetType") or "")

    entries = await list_entries(novel_id, target_type, str(plan.get("targetName") or "").strip())
    reply = await ainvoke_with_fallback(_editModel, _editModel_backup, [
        SystemMessage(content=SETTLE_PROMPT),
        HumanMessage(content=_settle_brief(state, plan, render_entries(target_type, entries)))])
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
        # 大纲这类不在 NEW_ENTITY_SPEC 里的只能改、不能新增（开书时就定死了）；关系（writerOnly）
        # 只能由写手在正文里造（两端角色认得出才连得上），这里也一律挡回。
        spec = NEW_ENTITY_SPEC.get(target_type)
        if spec is None or spec.get("writerOnly"):
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