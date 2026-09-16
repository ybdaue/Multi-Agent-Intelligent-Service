"""意图识别准确率 —— 四分类准确率 + 混淆矩阵 + 兜底率 + 任务栈一致率。

指标口径：
    准确率        primary_intent 与标注一致的 case 占比（四分类 draft / analyze / consult / chat）
    混淆矩阵      标注 × 预测 计数表，用来定位哪两类容易被混淆（analyze/consult 通常是重灾区）
    兜底率        走到 _intent_fallback 或输出非法意图的占比，越低说明模型严格 JSON 输出越稳
    任务栈一致率   pending_tasks 与标注**顺序完全一致**的占比（分类对但任务拆错算半失分）
    分桶召回       每个意图类别各自的召回率

取数：直接调用 agents.legal._intent_node，不运行编译图、不写任何库（见 _common 顶部说明）。

用法（在 agents-project 目录下）：
    python test/metrics/metric_intent.py
    python test/metrics/metric_intent.py --refresh --save
"""

import sys
from pathlib import Path

_METRICS_DIR = Path(__file__).resolve().parent
if str(_METRICS_DIR) not in sys.path:
    sys.path.insert(0, str(_METRICS_DIR))

import _common as C  # noqa: E402

INTENT_CLASSES = ["draft", "analyze", "consult", "chat"]
INVALID = "（无效意图）"


def main() -> None:
    args = C.arg_parser("意图识别准确率").parse_args()
    C.bootstrap()

    cases = [c for c in C.load_cases() if c.get("expect_intent")]
    cases = C.select(cases, args)
    traces = C.need_traces(cases, args)

    total = 0
    correct = 0
    fell_back = 0
    tasks_total = 0
    tasks_match = 0
    matrix: dict[str, dict[str, int]] = {}
    per_class = {c: {"total": 0, "hit": 0} for c in INTENT_CLASSES}
    failures: list[dict] = []

    for case in cases:
        trace = traces[case["id"]]
        intent = trace.get("intent") or {}
        expected = case["expect_intent"]
        predicted = intent.get("primary_intent")

        total += 1
        if intent.get("fell_back") or not intent.get("valid"):
            fell_back += 1

        key = predicted if predicted in INTENT_CLASSES else INVALID
        matrix.setdefault(expected, {}).setdefault(key, 0)
        matrix[expected][key] += 1

        if expected in per_class:
            per_class[expected]["total"] += 1

        if predicted == expected:
            correct += 1
            if expected in per_class:
                per_class[expected]["hit"] += 1
        else:
            failures.append(
                {
                    "case_id": case["id"],
                    "query": case["query"],
                    "expected": expected,
                    "predicted": predicted,
                    "error": intent.get("error"),
                    "note": case.get("note"),
                }
            )

        if case.get("expect_tasks") is not None:
            tasks_total += 1
            if list(intent.get("pending_tasks") or []) == list(case["expect_tasks"]):
                tasks_match += 1

    C.header("意图识别准确率")

    print(f"整体准确率    {C.pct(correct, total)}")
    print(f"兜底/无效率   {C.pct(fell_back, total)}   （越低越好）")
    print(f"任务栈一致率  {C.pct(tasks_match, tasks_total)}")

    print("\n分桶召回（每个意图类别自身被识别出的比例）：")
    for cls in INTENT_CLASSES:
        stat = per_class[cls]
        print(f"  {cls:<9} {C.pct(stat['hit'], stat['total'])}")

    print("\n混淆矩阵（行=标注，列=预测）：")
    cols = INTENT_CLASSES + [INVALID]
    print(f"  {'标注\\预测':<11}" + "".join(f"{c:>10}" for c in cols))
    for exp in INTENT_CLASSES:
        row = matrix.get(exp, {})
        print(f"  {exp:<11}" + "".join(f"{row.get(c, 0):>10}" for c in cols))

    if failures:
        print(f"\n误判明细（{len(failures)} 条）：")
        for f in failures:
            print(f"  [{f['case_id']}] 期望={f['expected']} 实际={f['predicted']} :: {f['query'][:34]}")
            if f.get("error"):
                print(f"        error={f['error']}")
    else:
        print("\n无误判。")

    if args.save:
        path = C.save_result(
            "intent",
            {
                "metric": "intent_accuracy",
                "n": total,
                "accuracy": round(correct / total, 4) if total else None,
                "fallback_rate": round(fell_back / total, 4) if total else None,
                "task_stack_match_rate": round(tasks_match / tasks_total, 4) if tasks_total else None,
                "per_class_recall": {
                    c: (round(s["hit"] / s["total"], 4) if s["total"] else None)
                    for c, s in per_class.items()
                },
                "confusion_matrix": matrix,
                "failures": failures,
            },
        )
        print(f"\n结果已写入：{path}")


if __name__ == "__main__":
    main()
