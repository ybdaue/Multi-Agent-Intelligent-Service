"""规划效率 —— 用了几步才把任务栈走完，有没有绕路/重复/撞上限。

指标口径（理论最小步数 = 标注任务数，每个任务恰好一次工具调用）：
    规划效率      理论最小工具调用数 / 实际工具调用数，1.0 表示一步不多余
    步数膨胀率     (实际 − 理论) / 理论，0 表示没有多余调用
    一次收敛率     stop_reason == completed（任务栈走完且模型主动收尾）的 case 占比
    硬停率         撞到 max_step 上限被迫终止的占比，越低越好（说明决策没有打转）
    重复任务率     至少重复调用过一次已完成任务的 case 占比
    越序率         至少一次没按任务栈顺序推进的 case 占比
    多余调用率     实际工具调用次数 > 理论最小次数的 case 占比

取数：在内存里逐轮调用 agents.legal._assistant_node，工具结果用合成 ToolMessage 替代，
不进入 ToolNode、不写任何库（见 _common 顶部说明）。

用法（在 agents-project 目录下）：
    python test/metrics/metric_planning.py
    python test/metrics/metric_planning.py --refresh --save
"""

import sys
from pathlib import Path

_METRICS_DIR = Path(__file__).resolve().parent
if str(_METRICS_DIR) not in sys.path:
    sys.path.insert(0, str(_METRICS_DIR))

import _common as C  # noqa: E402


def main() -> None:
    args = C.arg_parser("规划效率").parse_args()
    C.bootstrap()

    cases = C.select(C.load_cases(), args)
    traces = C.need_traces(cases, args)

    n = 0
    sum_theory = 0
    sum_actual = 0
    converged = 0
    hard_stop = 0
    repeat_cases = 0
    order_cases = 0
    extra_cases = 0
    details: list[dict] = []

    for case in cases:
        trace = traces[case["id"]]
        expected_tools = list(case.get("expect_tools") or [])
        actual_tools = list(trace.get("tools_seq") or [])
        steps = trace.get("steps") or []

        theory = len(expected_tools)
        actual = len(actual_tools)

        n += 1
        sum_theory += theory
        sum_actual += actual

        stop = trace.get("stop_reason")
        if stop == "completed":
            converged += 1
        if stop == "step_limit":
            hard_stop += 1

        has_repeat = any(s.get("is_repeat") for s in steps)
        has_out_of_order = any(
            s.get("tool") and not s.get("is_next_task") for s in steps
        )
        if has_repeat:
            repeat_cases += 1
        if has_out_of_order:
            order_cases += 1
        if actual > theory:
            extra_cases += 1

        details.append(
            {
                "case_id": case["id"],
                "query": case["query"],
                "theory_steps": theory,
                "actual_steps": actual,
                "actual_tools": actual_tools,
                "expected_tools": expected_tools,
                "stop_reason": stop,
                "has_repeat": has_repeat,
                "has_out_of_order": has_out_of_order,
            }
        )

    efficiency = (sum_theory / sum_actual) if sum_actual else None
    inflation = ((sum_actual - sum_theory) / sum_theory) if sum_theory else None

    C.header("规划效率")

    print(f"平均理论步数    {sum_theory / n:.2f}   （标注任务数，一次工具调用算一步）")
    print(f"平均实际步数    {sum_actual / n:.2f}   （实际发生的工具调用次数）")
    print(f"规划效率        {efficiency:.3f}" if efficiency is not None else "规划效率        n/a")
    print(
        f"步数膨胀率      {inflation:+.1%}" if inflation is not None else "步数膨胀率      n/a"
    )
    print()
    print(f"一次收敛率      {C.pct(converged, n)}   （任务栈走完并主动收尾）")
    print(f"硬停率          {C.pct(hard_stop, n)}   （撞 max_step 上限，越低越好）")
    print(f"重复任务率      {C.pct(repeat_cases, n)}   （至少重复执行过一次已完成任务）")
    print(f"越序率          {C.pct(order_cases, n)}   （至少一次未按任务栈顺序推进）")
    print(f"多余调用率      {C.pct(extra_cases, n)}   （实际调用次数多于理论最小次数）")

    wasteful = [
        d
        for d in details
        if d["has_repeat"] or d["has_out_of_order"] or d["stop_reason"] not in ("completed", "no_tool_call")
    ]
    if wasteful:
        print(f"\n需要看的 case（{len(wasteful)} 条）：")
        for d in wasteful:
            print(
                f"  [{d['case_id']}] 理论{d['theory_steps']}步/实际{d['actual_steps']}步 "
                f"stop={d['stop_reason']} repeat={d['has_repeat']} 越序={d['has_out_of_order']}"
            )
            print(f"        期望={d['expected_tools']} 实际={d['actual_tools']}")
    else:
        print("\n所有 case 都是最小步数收敛，无绕路。")

    if args.save:
        path = C.save_result(
            "planning",
            {
                "metric": "planning_efficiency",
                "n": n,
                "avg_theory_steps": round(sum_theory / n, 3) if n else None,
                "avg_actual_steps": round(sum_actual / n, 3) if n else None,
                "planning_efficiency": round(efficiency, 4) if efficiency is not None else None,
                "step_inflation": round(inflation, 4) if inflation is not None else None,
                "converged_rate": round(converged / n, 4) if n else None,
                "hard_stop_rate": round(hard_stop / n, 4) if n else None,
                "repeat_task_rate": round(repeat_cases / n, 4) if n else None,
                "out_of_order_rate": round(order_cases / n, 4) if n else None,
                "extra_call_rate": round(extra_cases / n, 4) if n else None,
                "details": details,
            },
        )
        print(f"\n结果已写入：{path}")


if __name__ == "__main__":
    main()
