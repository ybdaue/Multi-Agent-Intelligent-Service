"""Token 成本 —— 每条 case 消耗多少 token，以及成本集中在哪一环。

指标口径：
    总 token      意图识别 + 各轮调度 的输入/输出 token 之和
    每条 case 均值 总 token / case 数，可直接换算成"一次对话大概多少钱"
    每轮模型调用数 (1 次意图 + 调度轮次) / case 数，反映"话术是否啰嗦、有没有多余的模型往返"
    覆盖度        拿到 usage 的调用占比。闲聊轮的答复走流式，未开 stream_usage 拿不到用量；
                  这一栏就是用来暴露这个缺口的，不是 bug。

单价折算（可选）：--price-in / --price-out 传"元 / 百万 token"，按 DeepSeek 的公开价填即可。
    不传则只报 token 数（token 数才是客观量，价格随厂商变动，不写死在代码里）。

用法（在 agents-project 目录下）：
    python test/metrics/metric_token_cost.py
    python test/metrics/metric_token_cost.py --price-in 1 --price-out 2 --save
"""

import sys
from pathlib import Path

_METRICS_DIR = Path(__file__).resolve().parent
if str(_METRICS_DIR) not in sys.path:
    sys.path.insert(0, str(_METRICS_DIR))

import _common as C  # noqa: E402


def build_parser():
    p = C.arg_parser("Token 成本")
    p.add_argument("--price-in", type=float, default=0.0, help="输入单价（元 / 百万 token）")
    p.add_argument("--price-out", type=float, default=0.0, help="输出单价（元 / 百万 token）")
    return p


def _add(target: dict, usage: dict | None) -> None:
    if not usage:
        return
    for key in ("input", "output", "total"):
        target[key] += usage.get(key) or 0


def main(args) -> None:
    C.bootstrap()

    cases = [c for c in C.load_cases() if c.get("expect_intent")]
    cases = C.select(cases, args)
    traces = C.need_traces(cases, args)

    totals = {"input": 0, "output": 0, "total": 0}
    intent_totals = {"input": 0, "output": 0, "total": 0}
    round_totals = {"input": 0, "output": 0, "total": 0}

    calls_with_usage = 0
    calls_total = 0
    model_calls = 0
    per_case: list[dict] = []
    by_intent: dict[str, dict] = {}

    for case in cases:
        trace = traces[case["id"]]
        case_usage = {"input": 0, "output": 0, "total": 0}
        case_calls = 0

        intent = trace.get("intent") or {}
        if intent.get("latency_ms") is not None:  # 意图那一次调用
            case_calls += 1
            calls_total += 1
            if intent.get("usage"):
                calls_with_usage += 1
                _add(intent_totals, intent["usage"])
                _add(case_usage, intent["usage"])

        for step in trace.get("steps") or []:
            case_calls += 1
            calls_total += 1
            if step.get("usage"):
                calls_with_usage += 1
                _add(round_totals, step["usage"])
                _add(case_usage, step["usage"])

        _add(totals, case_usage)
        model_calls += case_calls

        bucket = by_intent.setdefault(
            case["expect_intent"], {"input": 0, "output": 0, "total": 0, "n": 0}
        )
        _add(bucket, case_usage)
        bucket["n"] += 1

        per_case.append(
            {
                "case_id": case["id"],
                "expected_intent": case["expect_intent"],
                "model_calls": case_calls,
                "tokens": dict(case_usage),
            }
        )

    n = len(cases)

    C.header("Token 成本")
    print(f"样本：{n} 条 case，共 {model_calls} 次模型调用\n")

    print(f"  {'环节':<14}{'输入 token':>14}{'输出 token':>14}{'合计':>14}")
    print("  " + "-" * 56)
    for label, agg in (
        ("意图识别", intent_totals),
        ("调度轮次", round_totals),
        ("总计", totals),
    ):
        print(f"  {label:<14}{agg['input']:>14,}{agg['output']:>14,}{agg['total']:>14,}")

    print()
    print(f"每条 case 平均 token   {totals['total'] / n:,.0f}")
    print(f"每条 case 平均模型调用 {model_calls / n:.2f} 次   （1 次意图 + 调度轮次）")
    print(f"用量覆盖度             {C.pct(calls_with_usage, calls_total)}")
    print("                      未覆盖的是闲聊轮：答复走流式且未开 stream_usage，拿不到 usage")

    print("\n按意图分桶（每条 case 平均 token）：")
    for intent, agg in sorted(
        by_intent.items(), key=lambda kv: -(kv[1]["total"] / kv[1]["n"] if kv[1]["n"] else 0)
    ):
        avg = agg["total"] / agg["n"] if agg["n"] else 0
        print(f"  {intent:<10}{agg['n']:>4} 条   avg={avg:>9,.0f} token   （{agg['total']:,} 合计）")

    if args.price_in or args.price_out:
        cost = (
            totals["input"] / 1_000_000 * args.price_in
            + totals["output"] / 1_000_000 * args.price_out
        )
        print(
            f"\n按单价 输入 {args.price_in} 元/M、输出 {args.price_out} 元/M 折算："
            f"合计 {cost:.4f} 元，每条 case 约 {cost / n:.6f} 元"
        )
    else:
        print("\n未传 --price-in/--price-out，只报 token 数（价格随厂商变动，不写死）。")

    if args.save:
        path = C.save_result(
            "token_cost",
            {
                "metric": "token_cost",
                "n": n,
                "model_calls": model_calls,
                "avg_model_calls_per_case": round(model_calls / n, 3),
                "usage_coverage": round(calls_with_usage / calls_total, 4) if calls_total else None,
                "totals": totals,
                "intent_totals": intent_totals,
                "round_totals": round_totals,
                "avg_tokens_per_case": round(totals["total"] / n, 1) if n else None,
                "by_intent": by_intent,
                "per_case": per_case,
            },
        )
        print(f"\n结果已写入：{path}")


if __name__ == "__main__":
    main(build_parser().parse_args())
