"""工具调用准确率 —— 工具选择是否选对、参数是否填全、闲聊时是否误调。

指标口径：
    序列准确率    整条工具调用序列与标注**顺序完全一致**的 case 占比
    单步准确率    每一轮选中的工具是否就是该轮"下一步必须完成"对应的工具
    参数完整率    该工具必填参数是否填全（analyze_document→file_id；consultor→question；
                  draft_document_agent→doc_type+requirement 或 original_file_id+revision_instructions）
    越序率        调了任务栈里排在后面的任务（选了非 next_task 的工具）
    重复调用率    调了已完成的工具（decision_prompt 明令禁止）
    闲聊误调率    标注期望"不调任何工具"（expect_tools 为空）却调了工具的占比

取数：直接调用 agents.legal._assistant_node，只读它返回的 tool_calls；工具本身不执行（见 _common）。

用法（在 agents-project 目录下）：
    python test/metrics/metric_tool_call.py
    python test/metrics/metric_tool_call.py --refresh --save
"""

import sys
from pathlib import Path

_METRICS_DIR = Path(__file__).resolve().parent
if str(_METRICS_DIR) not in sys.path:
    sys.path.insert(0, str(_METRICS_DIR))

import _common as C  # noqa: E402


def main() -> None:
    args = C.arg_parser("工具调用准确率").parse_args()
    C.bootstrap()

    # 所有 case 都参与：expect_tools 为空表示"这一轮不该调工具"，同样是被测行为
    cases = C.select(C.load_cases(), args)
    traces = C.need_traces(cases, args)

    seq_total = seq_hit = 0
    step_total = step_next = step_repeat = 0
    args_total = args_hit = 0
    no_tool_cases = no_tool_clean = 0
    failures: list[dict] = []
    missed_args: list[dict] = []

    for case in cases:
        trace = traces[case["id"]]
        expected_tools = list(case.get("expect_tools") or [])
        actual_tools = list(trace.get("tools_seq") or [])

        seq_total += 1
        if actual_tools == expected_tools:
            seq_hit += 1
        else:
            failures.append(
                {
                    "case_id": case["id"],
                    "query": case["query"],
                    "expected": expected_tools,
                    "actual": actual_tools,
                    "stop_reason": trace.get("stop_reason"),
                }
            )

        if not expected_tools:
            no_tool_cases += 1
            if not actual_tools:
                no_tool_clean += 1

        for step in trace.get("steps") or []:
            tool = step.get("tool")
            if not tool:
                continue
            step_total += 1
            if step.get("is_next_task"):
                step_next += 1
            if step.get("is_repeat"):
                step_repeat += 1
            if step.get("args_ok") is not None:
                args_total += 1
                if step["args_ok"]:
                    args_hit += 1
                else:
                    missed_args.append(
                        {
                            "case_id": case["id"],
                            "tool": tool,
                            "args": step.get("args"),
                            "round": step.get("round"),
                        }
                    )

    C.header("工具调用准确率")

    print(f"序列准确率    {C.pct(seq_hit, seq_total)}   （整条工具序列与标注一致）")
    print(f"单步准确率    {C.pct(step_next, step_total)}   （每轮都选中下一步该做的工具）")
    print(f"参数完整率    {C.pct(args_hit, args_total)}   （必填参数填全）")
    print(f"越序率        {C.pct(step_total - step_next, step_total)}   （越低越好）")
    print(f"重复调用率    {C.pct(step_repeat, step_total)}   （越低越好）")
    print(f"闲聊误调率    {C.pct(no_tool_cases - no_tool_clean, no_tool_cases)}   （该直答却调了工具）")

    if failures:
        print(f"\n序列不一致明细（{len(failures)} 条）：")
        for f in failures:
            print(f"  [{f['case_id']}] 期望={f['expected']} 实际={f['actual']} stop={f['stop_reason']}")
            print(f"        {f['query'][:40]}")
    else:
        print("\n全部序列一致。")

    if missed_args:
        print(f"\n参数缺失明细（{len(missed_args)} 条）：")
        for m in missed_args:
            print(f"  [{m['case_id']}] round={m['round']} tool={m['tool']} args={m['args']}")

    if args.save:
        path = C.save_result(
            "tool_call",
            {
                "metric": "tool_call_accuracy",
                "n_cases": seq_total,
                "sequence_accuracy": round(seq_hit / seq_total, 4) if seq_total else None,
                "step_accuracy": round(step_next / step_total, 4) if step_total else None,
                "args_completeness": round(args_hit / args_total, 4) if args_total else None,
                "out_of_order_rate": round((step_total - step_next) / step_total, 4) if step_total else None,
                "repeat_call_rate": round(step_repeat / step_total, 4) if step_total else None,
                "no_tool_false_positive_rate": (
                    round((no_tool_cases - no_tool_clean) / no_tool_cases, 4) if no_tool_cases else None
                ),
                "sequence_failures": failures,
                "missing_args": missed_args,
            },
        )
        print(f"\n结果已写入：{path}")


if __name__ == "__main__":
    main()
