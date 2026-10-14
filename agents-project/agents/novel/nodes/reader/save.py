"""save 节点（不调模型）：三份判词合并 + 字数校验，并把手上的审查问题落成影响台账行。"""
from langchain_core.runnables import RunnableConfig

from .helpers import _conflicts, _merge_reports, _parsed, _problem_rows
from .state import ReaderState


def save(state: ReaderState, config: RunnableConfig) -> dict:
    """收结论：三份判词合并 + 字数校验，并把手上的审查问题落成影响台账行。

    审查问题同时落成影响台账行：
      - 没过 → 本趟问题逐条成行（pending），把上一趟 reader 的行换掉；
      - 过了、且上一趟带过来 reader 行 → 那几行翻成已修复（fixed），说明重写后问题没了；
      - 过了、也没有带过来的行 → 不动台账（别把 editor 的设定影响行覆盖掉）。
    conflicts 由 pacing 判词给出，交父图 confirm_chapter 问用户定夺。
    editor 的设定影响行（detectedBy 不是 reader）始终原样保留。
    """
    review = _merge_reports(state)
    order = (state.get("active_chapter") or {}).get("chapter_order")
    existing = list(state.get("change_impact") or [])
    carried = [row for row in existing if row.get("detectedBy") == "reader"]
    others = [row for row in existing if row.get("detectedBy") != "reader"]

    if not review["passed"]:
        problems = (review.get("problems") or "").strip()
        # 判词没写出具体问题（比如只有解析失败）时别用空列表换掉上一趟的行。
        change_impact = others + _problem_rows(problems, order) if problems else existing
    elif carried:
        change_impact = others + [
            {**row, "status": "fixed", "resolution": "已按审查意见重写"} for row in carried
        ]
    else:
        change_impact = existing

    return {
        "chapter_review": review,
        "chapter_conflicts": _conflicts(_parsed(state.get("pacing_report") or "")),
        "change_impact": change_impact,
    }