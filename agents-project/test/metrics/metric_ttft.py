"""首字时间（TTFT）—— 用户从发消息到看见第一个字的时间。

为什么单独一档：完整往返时延会把"用户等多久才有反应"和"答案写多久"混在一起。
本项目的链路里，前半段（意图识别 + 调度轮）是 disable_streaming，前端**一个字都没有**，
用户的体感首字 = 前半段总耗时 + 最终答复流式的首字耗时。所以只测答复自身的 TTFT 会低估体感。

指标口径：
    答复/总结 TTFT   该次流式调用里首个 token 的到达时刻（相对本次调用开始）
    本次全程         该次流式调用的完整生成时间（首字 → 收尾）
    用户感知首字      闲聊：意图 + 答复TTFT
                     任务：意图 + 调度轮 + 总结TTFT
                     调度轮耗时取自缓存 trace，不重复调用模型

流式路径只有两条（靠 _common.ensure_ttft_probe 的回调捕获，不改仓库代码）：
    闲聊 → _assistant_node 内部的 MainModel(temperature=0.5)
    任务 → _summary_node 的 _summarizer_model（需 config.produce_summary=True）

数据库安全：只调用 _intent_node / _assistant_node / _summary_node 三个纯节点，不写库。

用法（在 agents-project 目录下，会真实调用模型）：
    python test/metrics/metric_ttft.py
    python test/metrics/metric_ttft.py --save
    python test/metrics/metric_ttft.py --ids chat-001,chat-002
"""

import sys
import time
from pathlib import Path

_METRICS_DIR = Path(__file__).resolve().parent
if str(_METRICS_DIR) not in sys.path:
    sys.path.insert(0, str(_METRICS_DIR))

import _common as C  # noqa: E402


async def measure_one(case: dict, probe, planning_ms: float) -> dict:
    """单条 case 的首字测量。planning_ms 由缓存的 trace 提供（任务类才有意义）。"""
    import agents.legal as L

    query = case["query"]
    has_file = bool(case.get("has_file"))

    # ── 1. 意图识别：非流式，期间前端无字可显示，但必须计入体感 ──
    t0 = time.perf_counter()
    base = C.make_state(query, has_file=has_file)
    intent_res = await L._intent_node(base, {})
    intent_ms = (time.perf_counter() - t0) * 1000
    upd, _fell_back = C._split_intent_result(intent_res)
    pending = list(upd.get("pending_tasks") or [])

    # 无待办任务时没有"调度轮"，缓存里那条 assistant 记录本身就是流式答复，
    # 再当成前半段相加会重复计数。只有任务类才把缓存里的调度耗时算进前半段。
    head_ms = planning_ms if pending else 0.0

    if not pending:
        # ── 闲聊：最终答复来自 assistant 的流式分支 ──
        state = C.make_state(query, has_file=has_file, pending_tasks=[], messages=base["messages"])
        probe.reset()
        t1 = time.perf_counter()
        await L._assistant_node(state, {})
        stream_total = (time.perf_counter() - t1) * 1000
        return {
            "case_id": case["id"],
            "intent": "chat",
            "stage": "闲聊答复",
            "intent_ms": round(intent_ms, 1),
            "head_ms": 0.0,
            "ttft_ms": _round(probe.ttft_ms),
            "stream_total_ms": round(stream_total, 1),
            "perceived_ttft_ms": _round(intent_ms + (probe.ttft_ms or stream_total)),
            "perceived_total_ms": round(intent_ms + stream_total, 1),
        }

    # ── 任务：最终答复来自 _summary_node 的流式输出 ──
    state = C.make_state(
        query, has_file=has_file, pending_tasks=pending, completed_tasks=pending
    )
    probe.reset()
    t1 = time.perf_counter()
    res = await L._summary_node(state, {"configurable": {"produce_summary": True}})
    stream_total = (time.perf_counter() - t1) * 1000
    if not res:  # completed_tasks 为空时会早返回，此处不该发生
        print(f"  ⚠️  {case['id']} summary 未执行，首字退回完整往返")
        return {
            "case_id": case["id"],
            "intent": case.get("expect_intent"),
            "stage": "（summary 未执行）",
            "intent_ms": round(intent_ms, 1),
            "head_ms": round(head_ms, 1),
            "ttft_ms": None,
            "stream_total_ms": None,
            "perceived_ttft_ms": round(intent_ms + head_ms, 1),
            "perceived_total_ms": round(intent_ms + head_ms, 1),
        }
    return {
        "case_id": case["id"],
        "intent": case.get("expect_intent"),
        "stage": "任务总结",
        "intent_ms": round(intent_ms, 1),
        "head_ms": round(head_ms, 1),
        "ttft_ms": _round(probe.ttft_ms),
        "stream_total_ms": round(stream_total, 1),
        "perceived_ttft_ms": _round(intent_ms + head_ms + (probe.ttft_ms or stream_total)),
        "perceived_total_ms": round(intent_ms + head_ms + stream_total, 1),
    }


def _round(value):
    return None if value is None else round(value, 1)


def _planning_ms_from_cache(cases: list[dict]) -> dict[str, float]:
    """调度轮总耗时 = trace 整链 - 意图耗时（部分节点，不重复调模型）。"""
    traces = C.trace_all(cases)
    out = {}
    for case in cases:
        t = traces[case["id"]]
        intent = (t.get("intent") or {}).get("latency_ms") or 0
        out[case["id"]] = max((t.get("total_latency_ms") or 0) - intent, 0)
    return out


def report(rows: list[dict], args) -> None:
    C.header("首字时间（TTFT）")

    stages = {}
    for r in rows:
        stages.setdefault(r["intent"] if r["intent"] in ("chat",) else "task", []).append(r)

    print(f"样本 {len(rows)} 条（TTFT 只在流式路径上有意义，全部为真实模型调用）\n")
    print(
        f"  {'case':<12}{'类型':<8}{'意图':>9}{'前半段':>9}{'TTFT':>9}"
        f"{'全程':>9}{'体感首字':>10}"
    )
    print("  " + "-" * 68)
    for r in sorted(rows, key=lambda x: (x["intent"] != "chat", -(x["perceived_ttft_ms"] or 0))):
        kind = "闲聊" if r["intent"] == "chat" else "任务"
        print(
            f"  {r['case_id']:<12}{kind:<8}{_ms(r['intent_ms']):>9}{_ms(r['head_ms']):>9}"
            f"{_ms(r['ttft_ms']):>9}{_ms(r['stream_total_ms']):>9}"
            f"{_ms(r['perceived_ttft_ms']):>10}"
        )

    for kind, label in (("chat", "闲聊"), ("task", "任务")):
        group = stages.get(kind) or []
        if not group:
            continue
        pt = [r["perceived_ttft_ms"] for r in group if r["perceived_ttft_ms"] is not None]
        tt = [r["ttft_ms"] for r in group if r["ttft_ms"] is not None]
        st = C.percentiles(pt)
        print(f"\n{label}（{len(group)} 条）用户感知首字：")
        print(f"  avg={_ms(st['avg'])}  p50={_ms(st['p50'])}  p90={_ms(st['p90'])}  max={_ms(st['max'])}")
        if tt:
            ts = C.percentiles(tt)
            print(
                f"  其中答复/总结自身 TTFT：avg={_ms(ts['avg'])}  p50={_ms(ts['p50'])}  "
                f"p90={_ms(ts['p90'])}  max={_ms(ts['max'])}"
            )

    print("\n说明：前半段（意图 + 调度轮）非流式，期间前端无字可显示，故计入体感首字。")
    print("      若前端在意图/调度期间有加载态，用户等待体感会更接近『前半段 + 答复TTFT』本身。")

    if args.save:
        summary = {}
        for kind, label in (("chat", "闲聊"), ("task", "任务")):
            group = stages.get(kind) or []
            if not group:
                continue
            summary[label] = {
                "n": len(group),
                "perceived_ttft_ms": C.percentiles(
                    [r["perceived_ttft_ms"] for r in group if r["perceived_ttft_ms"] is not None]
                ),
                "stream_ttft_ms": C.percentiles(
                    [r["ttft_ms"] for r in group if r["ttft_ms"] is not None]
                ),
                "perceived_total_ms": C.percentiles([r["perceived_total_ms"] for r in group]),
            }
        path = C.save_result(
            "ttft",
            {
                "metric": "ttft_ms",
                "n_cases": len(rows),
                "note": "用户感知首字 = 意图 + 调度轮 + 最终流式答复的首字；仅闲聊/任务总结是流式",
                "summary": summary,
                "cases": rows,
            },
        )
        print(f"\n结果已写入：{path}")


def _ms(value) -> str:
    return "n/a" if value is None else f"{value:.0f}"


def main(args) -> None:
    C.bootstrap()
    C.require_llm_key()

    cases = [c for c in C.load_cases() if c.get("expect_intent")]
    cases = C.select(cases, args)

    probe = C.ensure_ttft_probe()
    if probe is None:
        raise SystemExit("TTFT 探针不可用，无法测量首字时间。")

    print("从缓存 trace 取调度轮耗时（不重复调用模型）...")
    planning = _planning_ms_from_cache(cases)

    print(f"开始逐条实测首字（{len(cases)} 条，每条 1 次意图 + 1 次流式答复/总结）\n")
    rows = []
    for i, case in enumerate(cases, start=1):
        print(f"  [{i}/{len(cases)}] {case['id']} — {case['query'][:28]}")
        rows.append(C.run(measure_one(case, probe, planning.get(case["id"], 0.0))))

    report(rows, args)


if __name__ == "__main__":
    main(C.arg_parser("首字时间（TTFT）").parse_args())
