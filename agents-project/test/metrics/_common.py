"""指标检测共用底座。

职责：环境引导 / 标注集加载 / state 组装 / 决策链 trace 采集与缓存 / 结果落地。

数据库安全约束（改动本目录时务必保持）：
    只调用 agents.legal 的**节点函数**（_intent_node / _assistant_node）——它们是纯函数 +
    模型调用，不访问数据库。**不运行编译后的 legal_agent 图**，因为图内 checkin/update 直连
    PostgreSQL 写会话表、preprocessing 写 Chroma、draft_document_agent 写 created_file。
    工具执行只用内存里的合成 ToolMessage 模拟，不进入 ToolNode。
    （一个例外：本目录的检索指标只读 Chroma / PG，不做任何写入。）

费用约束：
    决策链 trace 缓存在 .cache/traces.json，多个指标文件共享同一份，避免重复调用模型。
    想强制重跑用 --refresh。
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

METRICS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = METRICS_DIR.parents[1]  # agents-project/
EVAL_SET = METRICS_DIR / "eval_set.jsonl"
CACHE_FILE = METRICS_DIR / ".cache" / "traces.json"
RESULTS_DIR = METRICS_DIR / "results"

# 每个工具的"必填参数"判定规则，供 metric_tool_call / metric_task_success 复用
def args_ok(tool: str, args: dict) -> bool | None:
    """工具参数是否完整。返回 None 表示该工具未定义必填参数规则。"""
    args = args or {}
    if tool == "analyze_document":
        return bool(str(args.get("file_id") or "").strip())
    if tool == "consultor":
        return bool(str(args.get("question") or "").strip())
    if tool == "draft_document_agent":
        fresh = bool(str(args.get("doc_type") or "").strip()) and bool(
            str(args.get("requirement") or "").strip()
        )
        revise = bool(str(args.get("original_file_id") or "").strip()) and bool(
            str(args.get("revision_instructions") or "").strip()
        )
        return fresh or revise
    return None


# 工具执行结果的内存替身：形状与真实工具返回一致，但不落任何库。
# analyze / draft 的返回会被 extract_tool_results 用 json.loads 解析，必须是合法 JSON。
_FAKE_TOOL_OUTPUT = {
    "analyze_document": json.dumps(
        {
            "summary": "评估用模拟分析结果",
            "risks": [
                {
                    "risk_level": "中",
                    "issue": "评估模拟风险项",
                    "suggestion": "评估模拟建议",
                    "legal_basis": "评估模拟依据",
                }
            ],
        },
        ensure_ascii=False,
    ),
    "consultor": "评估用模拟法律咨询答复。",
    "draft_document_agent": json.dumps(
        {"file_id": "eval_draft_file_0001", "filename": "评估模拟文书.docx"},
        ensure_ascii=False,
    ),
}


def bootstrap() -> Path:
    """把工程根目录加进 sys.path、加载 env、把控制台切到 UTF-8。返回 PROJECT_ROOT。

    必须在 import agents.* 之前调用：agents.legal 在模块级就会构造模型实例（读取 API key）。
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    _load_env()
    return PROJECT_ROOT


def _load_env() -> Path | None:
    from dotenv import load_dotenv

    mode = os.getenv("APP_ENV", "").strip().lower()
    if mode in ("production", "prod"):
        names = [".env.production", ".env.development", ".env"]
    else:
        names = [".env.development", ".env.production", ".env"]
    for name in names:
        path = PROJECT_ROOT / name
        if path.exists():
            load_dotenv(path, override=True)
            return path
    return None


def require_llm_key() -> None:
    """MainModel / IntentModel / CompressModel 都走 DeepSeek，缺 key 直接给出可读的退出信息。"""
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit(
            "缺少 DEEPSEEK_API_KEY：请在 agents-project/.env.development 配置后重试。"
        )


def run(coro):
    """Windows 上统一用 SelectorEventLoop（与本仓库既有测试一致）。"""
    import asyncio

    if sys.platform == "win32":
        try:
            return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
        except TypeError:  # Python < 3.12 没有 loop_factory
            return asyncio.run(coro)
    return asyncio.run(coro)


def load_cases(path: Path | None = None) -> list[dict]:
    """读标注集（JSONL，一行一条；# 开头与空行忽略）。"""
    path = path or EVAL_SET
    if not path.exists():
        raise SystemExit(f"标注集不存在：{path}")
    cases = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as e:
            raise SystemExit(f"标注集第 {lineno} 行不是合法 JSON：{e}") from e
        case.setdefault("id", f"case-{lineno:03d}")
        cases.append(case)
    return cases


def make_state(
    user_message: str,
    *,
    has_file: bool = False,
    pending_tasks=(),
    completed_tasks=(),
    step: int = 0,
    max_step: int = 10,
    messages=None,
    task_context=None,
    preference=(),
    summary: str = "",
    analysis_result=None,
    output_file=None,
    doc_ids=(),
) -> dict:
    """组装一个能被 _intent_node / _assistant_node 直接消费的 state。

    真实图里这些字段来自 MessagesState + checkpointer；这里手工给全，避免节点里 KeyError。
    """
    from langchain_core.messages import HumanMessage

    msgs = list(messages) if messages is not None else []
    if not any(isinstance(m, HumanMessage) for m in msgs):
        msgs = [HumanMessage(content=user_message)] + msgs

    doc_ids = list(doc_ids) if doc_ids else (["eval_file"] if has_file else [])
    file_source = (
        {"type": "db", "suffix": ".txt", "content": "eval", "file_id": "eval_file"}
        if has_file
        else None
    )
    return {
        "userId": 0,
        "user_message": user_message,
        "file_source": file_source,
        "doc_ids": doc_ids,
        "preference": list(preference),
        "summary": summary,
        "step": step,
        "max_step": max_step,
        "primary_intent": None,
        "pending_tasks": list(pending_tasks),
        "completed_tasks": list(completed_tasks),
        "task_context": dict(task_context or {}),
        "analysis_result": analysis_result,
        "answer_result": None,
        "output_file": output_file,
        "messages": msgs,
    }


def usage_of(resp) -> dict | None:
    """从模型响应取 token 用量；流式（未开 stream_usage）时返回 None。"""
    meta = getattr(resp, "usage_metadata", None)
    if not meta:
        return None
    return {
        "input": meta.get("input_tokens"),
        "output": meta.get("output_tokens"),
        "total": meta.get("total_tokens"),
    }


def _merge_usage(a: dict | None, b: dict | None) -> dict | None:
    if a is None and b is None:
        return None
    a = a or {}
    b = b or {}
    return {
        "input": (a.get("input") or 0) + (b.get("input") or 0),
        "output": (a.get("output") or 0) + (b.get("output") or 0),
        "total": (a.get("total") or 0) + (b.get("total") or 0),
    }


def _sum_usage(items) -> dict | None:
    total = None
    for item in items:
        total = _merge_usage(total, item)
    return total


def _usage_from_llm_result(response) -> dict | None:
    """从回调的 LLMResult 里抠 token 用量：优先 message.usage_metadata，退回 llm_output。"""
    try:
        total = None
        for generations in getattr(response, "generations", None) or []:
            for generation in generations:
                total = _merge_usage(total, usage_of(getattr(generation, "message", None)))
        if total is not None:
            return total
    except Exception:
        pass

    llm_output = getattr(response, "llm_output", None) or {}
    tu = llm_output.get("token_usage") or llm_output.get("usage") or {}
    if tu:
        return {
            "input": tu.get("prompt_tokens"),
            "output": tu.get("completion_tokens"),
            "total": tu.get("total_tokens"),
        }
    return None


# _intent_node 只返回解析后的 dict，不暴露响应对象，拿不到 token 用量。
# 该节点引用的是 agents.legal 的模块级全局 Intent_model，所以在调用时替换成带回调的绑定即可
# 采集到它的用量——只影响本进程的用量统计，不改仓库里任何代码，也不影响图的行为。
_tap = None
_tap_installed = False


def _ensure_usage_tap():
    global _tap, _tap_installed
    if _tap_installed:
        return _tap
    _tap_installed = True
    try:
        from langchain_core.callbacks import BaseCallbackHandler

        import agents.legal as legal_mod

        class _UsageTap(BaseCallbackHandler):
            def __init__(self):
                super().__init__()
                self.calls: list[dict] = []

            def on_llm_end(self, response, **kwargs):
                usage = _usage_from_llm_result(response)
                if usage:
                    self.calls.append(usage)

        _tap = _UsageTap()
        legal_mod.Intent_model = legal_mod.Intent_model.with_config(callbacks=[_tap])
    except Exception as e:
        print(f"  ⚠️  意图识别用量采集未启用（{type(e).__name__}: {e}），Token 成本会少算意图那一次调用")
        _tap = None
    return _tap


_ttft_probe = None
_ttft_installed = False


def ensure_ttft_probe():
    """把两处**流式**模型裹上首字回调，返回的探针用 reset() / ttft_ms 读首字耗时。

    本项目只有两处流式：闲聊答复（_assistant_node 内部的 MainModel）与任务收尾
    （_summary_node 用的 _summarizer_model）。意图识别与调度轮都是 disable_streaming=True，
    不吐 token，所以"用户感知的首字"必须把这两段耗时也算进去（见 metric_ttft）。

    只在本进程内替换 agents.legal 的模块级引用，不改仓库代码、不影响图行为、不碰数据库。
    """
    global _ttft_probe, _ttft_installed
    if _ttft_installed:
        return _ttft_probe
    _ttft_installed = True
    try:
        from langchain_core.callbacks import BaseCallbackHandler

        import agents.legal as legal_mod

        class _TTFTProbe(BaseCallbackHandler):
            def __init__(self):
                super().__init__()
                self.t0: float | None = None
                self.ttft_ms: float | None = None

            def reset(self):
                self.t0 = None
                self.ttft_ms = None

            def _start(self):
                self.t0 = time.perf_counter()
                self.ttft_ms = None

            def on_llm_start(self, *args, **kwargs):
                self._start()

            def on_chat_model_start(self, *args, **kwargs):
                self._start()

            def on_llm_new_token(self, token, **kwargs):
                if self.ttft_ms is None and self.t0 is not None:
                    self.ttft_ms = (time.perf_counter() - self.t0) * 1000

        probe = _TTFTProbe()
        real_main = legal_mod.MainModel

        def _main_factory(*a, **k):
            return real_main(*a, **k).with_config(callbacks=[probe])

        legal_mod.MainModel = _main_factory
        legal_mod._summarizer_model = legal_mod._summarizer_model.with_config(
            callbacks=[probe]
        )
        _ttft_probe = probe
    except Exception as e:
        print(f"  ⚠️  TTFT 探针未启用（{type(e).__name__}: {e}），首字时间会退化为完整往返")
        _ttft_probe = None
    return _ttft_probe


def _split_intent_result(result) -> tuple[dict, bool]:
    """_intent_node 正常返回 dict，兜底/无效意图时返回 Command(update=..., goto=END)。

    注意：不能用 getattr(result, "update", None) 判类型——dict 自己就有 update 方法，
    会把正常返回误判成兜底分支。
    """
    if isinstance(result, dict):
        return dict(result), False
    update = getattr(result, "update", None)
    return dict(update or {}), True


def _cache_key(case: dict) -> str:
    fingerprint = json.dumps(
        {
            "q": case.get("query", ""),
            "f": bool(case.get("has_file")),
            "t": case.get("expect_tasks") or [],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"{case['id']}::{hashlib.sha1(fingerprint.encode('utf-8')).hexdigest()[:10]}"


async def _collect_one(case: dict, tap=None) -> dict:
    """跑一条 case 的内存决策链：意图 → 逐轮调度（工具执行用合成 ToolMessage 替代）。

    全程只调用节点函数，不编译图、不写任何库。
    """
    from langchain_core.messages import ToolMessage

    from agents.legal import TOOL_TO_TASK, _assistant_node, _intent_node

    query = case.get("query", "")
    has_file = bool(case.get("has_file"))
    max_step = int(case.get("max_step", 10))

    trace: dict = {
        "case_id": case["id"],
        "query": query,
        "has_file": has_file,
        "expect": {
            "intent": case.get("expect_intent"),
            "tasks": case.get("expect_tasks") or [],
            "tools": case.get("expect_tools") or [],
        },
        "intent": None,
        "steps": [],
        "tools_seq": [],
        "stop_reason": None,
        "total_latency_ms": 0.0,
        "total_usage": None,
    }

    # ── 1. 意图识别（1 次模型调用）──
    tap_before = len(tap.calls) if tap else 0
    t0 = time.perf_counter()
    try:
        raw = await _intent_node(
            make_state(query, has_file=has_file, max_step=max_step), None
        )
        intent_dt = (time.perf_counter() - t0) * 1000
        update, fell_back = _split_intent_result(raw)
        trace["intent"] = {
            "primary_intent": update.get("primary_intent"),
            "pending_tasks": list(update.get("pending_tasks") or []),
            "task_context": update.get("task_context") or {},
            "valid": update.get("primary_intent") is not None,
            "fell_back": fell_back,
            "latency_ms": round(intent_dt, 1),
            "usage": _sum_usage(tap.calls[tap_before:]) if tap else None,
            "error": update.get("error"),
        }
        trace["total_latency_ms"] += intent_dt
    except Exception as e:  # 模型不可用等
        trace["intent"] = {
            "primary_intent": None,
            "pending_tasks": [],
            "task_context": {},
            "valid": False,
            "fell_back": True,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "usage": _sum_usage(tap.calls[tap_before:]) if tap else None,
            "error": f"{type(e).__name__}: {e}",
        }
        trace["stop_reason"] = "intent_exception"
        return trace

    if not trace["intent"]["valid"]:
        trace["stop_reason"] = "intent_invalid"
        return trace

    pending = trace["intent"]["pending_tasks"]

    # ── 2. 逐轮调度（每轮 1 次模型调用）──
    # 无待办任务时也跑一轮：这条路径是闲聊直答，同样要计入时延/用量/工具准确率（此时不应有工具）。
    messages = list(make_state(query, has_file=has_file)["messages"])
    state = make_state(query, has_file=has_file, pending_tasks=pending, messages=messages)
    analysis_result = None
    output_file = None

    for round_index in range(max_step + 2):  # +2 兜底：允许一轮无工具的收尾
        t0 = time.perf_counter()
        try:
            res = await _assistant_node(state, {})
        except Exception as e:
            trace["steps"].append(
                {
                    "round": round_index,
                    "tool": None,
                    "round_latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "error": f"{type(e).__name__}: {e}",
                }
            )
            trace["stop_reason"] = "assistant_exception"
            break
        round_dt = (time.perf_counter() - t0) * 1000
        trace["total_latency_ms"] += round_dt

        if not isinstance(res, dict):
            # 节点兜底分支返回 Command（dict 自带 update 方法，不能拿它判类型）
            update = getattr(res, "update", None) or {}
            trace["steps"].append(
                {
                    "round": round_index,
                    "tool": None,
                    "round_latency_ms": round(round_dt, 1),
                    "error": str(update.get("error")),
                }
            )
            trace["stop_reason"] = "assistant_fallback"
            break

        ai = res["messages"][-1]
        usage = usage_of(ai)
        trace["total_usage"] = _merge_usage(trace["total_usage"], usage)
        step_now = int(res.get("step", state["step"]))
        if res.get("analysis_result") is not None:
            analysis_result = res["analysis_result"]
        if res.get("output_file") is not None:
            output_file = res["output_file"]

        calls = getattr(ai, "tool_calls", None) or []

        if not calls:
            # 没有工具调用 = 本轮链路的终点（任务跑完 / 闲聊直答 / 撞步数上限）
            done = set(res.get("completed_tasks") or [])
            remaining = [t for t in pending if t not in done]
            if step_now >= max_step:
                reason = "step_limit"
            elif pending and not remaining:
                reason = "completed"
            else:
                reason = "no_tool_call"
            trace["steps"].append(
                {
                    "round": round_index,
                    "tool": None,
                    "step_after": step_now,
                    "round_latency_ms": round(round_dt, 1),
                    "usage": usage,
                    "is_final": True,
                }
            )
            trace["stop_reason"] = reason
            break

        call = calls[0]
        tool = call.get("name")
        args = call.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}

        done_before = set(state["completed_tasks"])
        remaining_before = [t for t in pending if t not in done_before]
        next_task = remaining_before[0] if remaining_before else None
        mapped = TOOL_TO_TASK.get(tool)

        trace["steps"].append(
            {
                "round": round_index,
                "tool": tool,
                "args": args,
                "args_ok": args_ok(tool, args),
                "next_task": next_task,
                "is_next_task": mapped == next_task,
                "is_repeat": mapped in done_before,
                "step_after": step_now,
                "round_latency_ms": round(round_dt, 1),
                "usage": usage,
                "is_final": False,
            }
        )
        trace["tools_seq"].append(tool)

        # 合成工具结果：形状对齐真实 ToolNode 产物，但不执行、不落库
        messages = list(state["messages"]) + [
            ai,
            ToolMessage(
                content=_FAKE_TOOL_OUTPUT.get(tool, "评估用模拟工具结果"),
                name=tool,
                tool_call_id=call.get("id") or f"eval-{round_index}",
            ),
        ]
        state = make_state(
            query,
            has_file=has_file,
            pending_tasks=pending,
            completed_tasks=res.get("completed_tasks") or [],
            step=step_now,
            max_step=max_step,
            messages=messages,
            analysis_result=analysis_result,
            output_file=output_file,
        )
    else:
        trace["stop_reason"] = "loop_guard"

    trace["total_latency_ms"] = round(trace["total_latency_ms"], 1)
    return trace


def recompute_step_order(trace: dict, case: dict) -> None:
    """按标注的任务栈（expect_tasks）重算每步的 is_next_task / is_repeat。

    为什么要独立重算：_collect_one 里逐轮推进时，completed_tasks 要等该轮返回才更新，
    直接用 state 里的值会滞后一轮，把顺序正确的 case 误判成越序。这里以标注的规范
    依赖顺序为准，回放实际工具序列重算，对 fresh 和缓存 trace 都一致。
    判定同时写入 trace["tools_seq_ok"]，便于其它指标直接读。
    """
    from agents.legal import TOOL_TO_TASK

    order = [t for t in (case.get("expect_tasks") or [])]
    done: set[str] = set()
    ok = True
    for step in trace.get("steps") or []:
        tool = step.get("tool")
        if not tool:
            continue
        mapped = TOOL_TO_TASK.get(tool)
        if mapped is None or mapped not in order:
            # 该工具不在标注任务栈里（多余调用 / 计划跑偏），单步不算命中
            step["is_next_task"] = False
            step["is_repeat"] = mapped in done
            ok = False
        else:
            earlier = [t for t in order[: order.index(mapped)] if t not in done]
            step["is_next_task"] = not earlier
            step["is_repeat"] = mapped in done
            if earlier:
                ok = False
        if mapped:
            done.add(mapped)
    trace["tools_seq_ok"] = ok


def trace_all(cases: list[dict], *, refresh: bool = False) -> dict[str, dict]:
    """采集全部 case 的决策链，返回 {case_id: trace}。

    带 .cache/traces.json 缓存：命中即复用，避免每个指标文件都重新烧一遍模型调用。
    """
    cache: dict[str, dict] = {}
    if CACHE_FILE.exists() and not refresh:
        try:
            cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache = {}

    traces: dict[str, dict] = {}
    pending_collect = []
    for case in cases:
        key = _cache_key(case)
        hit = cache.get(key)
        if hit is not None and not refresh:
            traces[case["id"]] = hit
        else:
            pending_collect.append((key, case))

    if pending_collect:
        tap = _ensure_usage_tap()
        total = len(pending_collect)
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        for i, (key, case) in enumerate(pending_collect, start=1):
            print(f"  [{i}/{total}] 采集决策链: {case['id']} — {case.get('query', '')[:28]}")
            trace = run(_collect_one(case, tap))
            cache[key] = trace
            traces[case["id"]] = trace
            # 逐条落盘：中途被打断也不丢已经花掉的模型调用
            CACHE_FILE.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        print(f"  trace 缓存已更新：{CACHE_FILE}")
    else:
        print(f"  全部命中 trace 缓存（{CACHE_FILE.name}），未产生模型调用")

    for case in cases:
        recompute_step_order(traces[case["id"]], case)

    return traces


def arg_parser(description: str):
    """各指标文件的统一命令行入口；需要额外参数的指标文件在返回的 parser 上再 add_argument。"""
    import argparse

    p = argparse.ArgumentParser(description=description)
    p.add_argument("--refresh", action="store_true", help="忽略 trace 缓存重新采集（会真实调用模型）")
    p.add_argument("--limit", type=int, default=0, help="只取前 N 条 case（0 = 全部）")
    p.add_argument("--ids", default="", help="只跑指定 case id，逗号分隔")
    p.add_argument("--save", action="store_true", help="把结果写入 results/<指标名>.json")
    return p


def select(cases: list[dict], args) -> list[dict]:
    if getattr(args, "ids", ""):
        want = {s.strip() for s in args.ids.split(",") if s.strip()}
        cases = [c for c in cases if c["id"] in want]
    if getattr(args, "limit", 0):
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("筛选后没有待测 case，检查 --ids / --limit。")
    return cases


def need_traces(cases: list[dict], args) -> dict[str, dict]:
    """校验 key → 采集（或读缓存）决策链。所有依赖模型调用的指标都该先走这里。"""
    require_llm_key()
    print(f"待测 {len(cases)} 条，开始采集决策链...")
    return trace_all(cases, refresh=bool(getattr(args, "refresh", False)))


# ── 结果输出 ──────────────────────────────────────────────────────────

def save_result(name: str, payload: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def percentiles(values: list[float]) -> dict:
    """p50/p90/p95/max + 均值。空列表返回全 None。"""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return {"n": 0, "avg": None, "p50": None, "p90": None, "p95": None, "max": None}
    return {
        "n": len(vals),
        "avg": round(statistics.fmean(vals), 1),
        "p50": round(_pick(vals, 0.50), 1),
        "p90": round(_pick(vals, 0.90), 1),
        "p95": round(_pick(vals, 0.95), 1),
        "max": round(vals[-1], 1),
    }


def _pick(sorted_vals: list[float], q: float) -> float:
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def pct(hit: int, total: int) -> str:
    if not total:
        return "n/a"
    return f"{hit / total * 100:.1f}% ({hit}/{total})"


def header(title: str) -> None:
    print()
    print("=" * 68)
    print(title)
    print("=" * 68)
