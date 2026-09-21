"""任务成功率 —— 决策链端到端是否达标（复合指标）。

指标口径（成功 = 三个条件全满足，按下述优先级归因首个失败环节）：
    1. 意图识别正确        primary_intent == 标注
    2. 工具序列正确        实际工具调用序列 == 标注（顺序敏感）
    3. 参数完整            每个被调用工具的必填参数都填全

为什么是"决策链成功率"而不是"产物质量成功率"：
    为了完全不写数据库，本脚本**不真正执行工具**——不生成 docx、不写 legal_created_file、
    不跑真实文件分析。因此它衡量的是"Agent 是否走对了流程"，而不是"生成的文书好不好"。
    产物质量（文书要素是否齐全、风险是否命中标注点）需要另建评估集并真实执行，见本文件末尾说明。

取数：内存决策链，见 _common 顶部说明。

用法（在 agents-project 目录下）：
    python test/metrics/metric_task_success.py
    python test/metrics/metric_task_success.py --refresh --save
"""

import sys
from pathlib import Path

_METRICS_DIR = Path(__file__).resolve().parent
if str(_METRICS_DIR) not in sys.path:
    sys.path.insert(0, str(_METRICS_DIR))

import _common as C  # noqa: E402

STAGE_INTENT = "意图识别"
STAGE_TOOLS = "工具序列"
STAGE_ARGS = "工具参数"


def main() -> None:
    args = C.arg_parser("任务成功率（决策链）").parse_args()
    C.bootstrap()

    cases = [c for c in C.load_cases() if c.get("expect_intent")]
    cases = C.select(cases, args)
    traces = C.need_traces(cases, args)

    total = 0
    success = 0
    buckets: dict[str, dict[str, int]] = {}
    failures: list[dict] = []

    for case in cases:
        trace = traces[case["id"]]
        expected_intent = case["expect_intent"]
        expected_tools = list(case.get("expect_tools") or [])
        intent = trace.get("intent") or {}
        predicted_intent = intent.get("primary_intent")
        actual_tools = list(trace.get("tools_seq") or [])
        args_bad = [
            s for s in (trace.get("steps") or []) if s.get("args_ok") is False
        ]

        total += 1
        bucket = buckets.setdefault(
            expected_intent, {"total": 0, "hit": 0}
        )
        bucket["total"] += 1

        if predicted_intent != expected_intent:
            failed_stage = STAGE_INTENT
        elif actual_tools != expected_tools:
            failed_stage = STAGE_TOOLS
        elif args_bad:
            failed_stage = STAGE_ARGS
        else:
            failed_stage = None

        if failed_stage is None:
            success += 1
            bucket["hit"] += 1
        else:
            failures.append(
                {
                    "case_id": case["id"],
                    "query": case["query"],
                    "failed_stage": failed_stage,
                    "expected_intent": expected_intent,
                    "predicted_intent": predicted_intent,
                    "expected_tools": expected_tools,
                    "actual_tools": actual_tools,
                    "bad_args": [
                        {"tool": s.get("tool"), "args": s.get("args")} for s in args_bad
                    ],
                    "stop_reason": trace.get("stop_reason"),
                }
            )

    stages = [STAGE_INTENT, STAGE_TOOLS, STAGE_ARGS]
    stage_counts = {s: sum(1 for f in failures if f["failed_stage"] == s) for s in stages}

    C.header("任务成功率（决策链）")

    print(f"整体成功率      {C.pct(success, total)}")
    print(f"失败 {len(failures)} 条，按首个失败环节归因：")
    for s in stages:
        print(f"  {s:<8} {stage_counts[s]:>3} 条")

    print("\n按意图分桶：")
    for intent_name, stat in buckets.items():
        print(f"  {intent_name:<9} {C.pct(stat['hit'], stat['total'])}")

    if failures:
        print(f"\n失败明细（{len(failures)} 条）：")
        for f in failures:
            print(f"  [{f['case_id']}] 卡在 {f['failed_stage']} :: {f['query'][:32]}")
            print(
                f"        意图 {f['expected_intent']}→{f['predicted_intent']} | "
                f"工具 {f['expected_tools']}→{f['actual_tools']} | stop={f['stop_reason']}"
            )
            if f["bad_args"]:
                print(f"        参数不全：{f['bad_args']}")
    else:
        print("\n全部达标。")

    print(
        "\n注意：本指标衡量决策链（意图→规划→工具选择），不含文书/风险报告等产物质量。"
        "\n      产物质量需要真实执行工具并另建标准答案，会写库，不在本目录的约束范围内。"
    )

    if args.save:
        path = C.save_result(
            "task_success",
            {
                "metric": "task_success_rate_decision_chain",
                "n": total,
                "success_rate": round(success / total, 4) if total else None,
                "failure_by_stage": stage_counts,
                "per_intent": {
                    k: {
                        "total": v["total"],
                        "hit": v["hit"],
                        "rate": round(v["hit"] / v["total"], 4) if v["total"] else None,
                    }
                    for k, v in buckets.items()
                },
                "failures": failures,
                "caveat": "仅覆盖决策链，不含产物质量；不执行工具、不写库",
            },
        )
        print(f"\n结果已写入：{path}")


if __name__ == "__main__":
    main()
