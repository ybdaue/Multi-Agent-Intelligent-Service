"""响应时间 —— 意图识别 / 单轮调度 / 整条决策链 / 检索 的时延分布。

指标口径：
    意图识别时延      一次 IntentModel 调用的完整往返
    单轮调度时延      一次 _assistant_node 的完整往返（一次调度决策，可能发起工具调用）
    整条决策链时延    意图 + 该轮全部调度轮次（**不含**真实工具执行耗时，工具是内存模拟的）
    检索时延          --with-retrieval 时附加；线上 retrieve_law 的完整链路耗时

⚠️ 边界说清楚（面试会被追问）：
    这里记的是**完整往返时延**，不是首 token 时延（TTFT）。调度节点走的是非流式
    invoke_assistant_model，流式只出现在闲聊轮与最终答复。要报 TTFT 需要另加流式探针，
    本脚本不覆盖。

用法（在 agents-project 目录下）：
    python test/metrics/metric_latency.py
    python test/metrics/metric_latency.py --with-retrieval --save
"""

import sys
import time
from pathlib import Path

_METRICS_DIR = Path(__file__).resolve().parent
if str(_METRICS_DIR) not in sys.path:
    sys.path.insert(0, str(_METRICS_DIR))

import _common as C  # noqa: E402


def build_parser():
    p = C.arg_parser("响应时间")
    p.add_argument(
        "--with-retrieval",
        action="store_true",
        help="附加测量线上检索链路（retrieve_law._retrieve_fused）的时延；只读 Chroma/PG",
    )
    return p


def main(args) -> None:
    C.bootstrap()

    cases = [c for c in C.load_cases() if c.get("expect_intent")]
    cases = C.select(cases, args)
    traces = C.need_traces(cases, args)

    intent_ms: list[float] = []
    round_ms: list[float] = []
    chain_ms: list[float] = []
    by_intent: dict[str, list[float]] = {}

    for case in cases:
        trace = traces[case["id"]]
        intent = trace.get("intent") or {}
        if intent.get("latency_ms") is not None:
            intent_ms.append(intent["latency_ms"])

        for step in trace.get("steps") or []:
            if step.get("round_latency_ms") is not None:
                round_ms.append(step["round_latency_ms"])

        chain = trace.get("total_latency_ms")
        if chain is not None:
            chain_ms.append(chain)
            by_intent.setdefault(case["expect_intent"], []).append(chain)

    C.header("响应时间（完整往返时延，非 TTFT）")
    print(f"样本：{len(cases)} 条 case / {len(round_ms)} 次调度调用\n")

    groups = [
        ("意图识别", intent_ms),
        ("单轮调度", round_ms),
        ("整条决策链", chain_ms),
    ]
    print(f"  {'环节':<14}{'n':>5}{'avg':>10}{'p50':>10}{'p90':>10}{'p95':>10}{'max':>10}")
    print("  " + "-" * 69)
    summary = {}
    for label, values in groups:
        st = C.percentiles(values)
        print(
            f"  {label:<14}{st['n']:>5}"
            f"{_ms(st['avg']):>10}{_ms(st['p50']):>10}{_ms(st['p90']):>10}"
            f"{_ms(st['p95']):>10}{_ms(st['max']):>10}"
        )
        summary[label] = st

    print("\n整条决策链按意图分桶（闲聊应最快——无任务直答、不绑工具）：")
    for intent, values in sorted(by_intent.items(), key=lambda kv: -(C.percentiles(kv[1])["avg"] or 0)):
        st = C.percentiles(values)
        print(f"  {intent:<10}{st['n']:>4} 条   avg={_ms(st['avg'])}  p90={_ms(st['p90'])}  max={_ms(st['max'])}")

    if args.with_retrieval:
        _measure_retrieval(cases, summary)

    if args.save:
        path = C.save_result(
            "latency",
            {
                "metric": "latency_ms",
                "n_cases": len(cases),
                "note": "完整往返时延；不含真实工具执行；非 TTFT",
                "stages": summary,
                "chain_by_intent": {
                    k: C.percentiles(v) for k, v in by_intent.items()
                },
            },
        )
        print(f"\n结果已写入：{path}")


def _measure_retrieval(cases: list[dict], summary: dict) -> None:
    """附加测量线上检索链路时延。只读 Chroma / PG。"""
    from agents.utils.RAG import init, is_ready

    init()
    if not is_ready():
        print("\n⚠️  跳过检索时延：RAG 未就绪（Chroma:8000 或本地 embedding 模型缺失）。")
        return

    import agents.legal.tools.retrieve_law as RL

    targets = [c for c in cases if c.get("retrieval_keywords") or c.get("expect_parent_ids")]
    if not targets:
        targets = cases[: min(6, len(cases))]

    latencies = []
    print(f"\n检索链路时延（retrieve_law 完整链路，{len(targets)} 条查询）：")
    for case in targets:
        t0 = time.perf_counter()
        hits = RL._retrieve_fused(case["query"])
        dt = (time.perf_counter() - t0) * 1000
        latencies.append(dt)
        print(f"  {dt:8.1f} ms  命中 {len(hits)} 个父块  {case['query'][:30]}")

    st = C.percentiles(latencies)
    print(
        f"  合计  avg={_ms(st['avg'])}  p50={_ms(st['p50'])}  p90={_ms(st['p90'])}  max={_ms(st['max'])}"
    )
    summary["检索链路（线上 retrieve_law）"] = st


def _ms(value) -> str:
    return "n/a" if value is None else f"{value:.0f}"


if __name__ == "__main__":
    main(build_parser().parse_args())
