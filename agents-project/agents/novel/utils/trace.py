"""调试用：节点进出各打一行，调式时能看清这一轮走到了哪个节点、走了多久、往哪儿去。

只打标准输出，不动 state、不动控制流，不要了把节点上的 traced(...) 摘掉即可。
**别用花哨符号**：Windows 控制台是 GBK，不在码表里的字符直接 UnicodeEncodeError。
"""
import functools
import inspect
import time

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.errors import GraphBubbleUp

_PREFIX = "[novel]"


class LlmWatch(BaseCallbackHandler):
    """挂在某个模型实例上，观察它到底有没有被调用、生成了多久、吐出多少。

    只打标准输出、不加任何图结构：回调挂在模型实例上，子图该怎么流式还怎么流式（正文 token
    照旧逐字出去）。run_id 认每次模型调用 —— 写手若 ReAct 反复调模型会看到一串，卡在第几次
    一眼可见。
    """

    def __init__(self, label: str = "llm"):
        self._label = label
        self._count = 0
        self._began: dict = {}
        self._chars: dict = {}
        self._no: dict = {}

    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kwargs):
        self._count += 1
        self._began[run_id] = time.monotonic()
        self._chars[run_id] = 0
        self._no[run_id] = self._count
        print(f"{_PREFIX} >> {self._label} 请求模型（第 {self._count} 次）...", flush=True)

    def on_llm_new_token(self, token, *, run_id=None, **kwargs):
        self._chars[run_id] = self._chars.get(run_id, 0) + len(token or "")

    def on_llm_end(self, response, *, run_id=None, **kwargs):
        no = self._no.pop(run_id, "?")
        began = self._began.pop(run_id, None)
        chars = self._chars.pop(run_id, 0)
        took = time.monotonic() - began if began else 0.0
        print(
            f"{_PREFIX} << {self._label} 模型返回（第 {no} 次）"
            f"用时 {took:.1f}s，流式 {chars} 字{_calls(response)}",
            flush=True,
        )

    def on_llm_error(self, error, *, run_id=None, **kwargs):
        self._no.pop(run_id, None)
        self._began.pop(run_id, None)
        self._chars.pop(run_id, 0)
        print(f"{_PREFIX} !! {self._label} 模型出错：{type(error).__name__}: {error}", flush=True)


def _calls(response) -> str:
    """模型这一轮有没有要调工具 / 用了多少 token —— 写手反复调工具在这儿看得见。"""
    try:
        message = response.generations[0][0].message
    except Exception:
        return ""
    calls = getattr(message, "tool_calls", None) or []
    if calls:
        names = "、".join(str(call.get("name")) for call in calls)
        return f"；模型要调工具：{names}"
    meta = getattr(message, "usage_metadata", None) or {}
    if meta:
        return f"；token 入 {meta.get('input_tokens', 0)} / 出 {meta.get('output_tokens', 0)}"
    return ""


def traced(name: str):
    """给节点套一层"开始 / 结束"的打印。sync、async 都认（图里的节点两种都有）。

    functools.wraps 不能省：langgraph 按 inspect.signature 的形参名与注解往里注
    state / config / store，签名得原样透出去。
    """

    def decorate(func):
        def begin() -> float:
            print(f"{_PREFIX} >> {name} 开始", flush=True)
            return time.monotonic()

        def finish(began: float, result) -> None:
            print(
                f"{_PREFIX} << {name} 结束 {time.monotonic() - began:.1f}s{_tail(result)}",
                flush=True,
            )

        def broken(exc: BaseException) -> None:
            print(f"{_PREFIX} !! {name} 出错：{type(exc).__name__}: {exc}", flush=True)

        def paused() -> None:
            print(f"{_PREFIX} << {name} 暂停（等用户答复）", flush=True)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                began = begin()
                try:
                    result = await func(*args, **kwargs)
                except GraphBubbleUp:
                    # interrupt() 是靠异常把控制权弹回图里，不是出错；这不算失败，
                    # 只是这一轮停在这儿等人回话，下一句答复带着同一个 thread 接着跑。
                    paused()
                    raise
                except Exception as exc:
                    broken(exc)
                    raise
                finish(began, result)
                return result

        else:

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                began = begin()
                try:
                    result = func(*args, **kwargs)
                except GraphBubbleUp:
                    paused()
                    raise
                except Exception as exc:
                    broken(exc)
                    raise
                finish(began, result)
                return result

        return wrapper

    return decorate


def _tail(result) -> str:
    """结束那行的尾巴：这一步往哪儿去了、交回了什么。看流程最要紧的两样。"""
    goto = getattr(result, "goto", None)
    if goto:
        return f" -> goto={goto}"
    if result is None:
        return ""
    if isinstance(result, dict):
        return f" -> {'、'.join(str(key) for key in result)}" if result else " -> 无更新"
    return ""
