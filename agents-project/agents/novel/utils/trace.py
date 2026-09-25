"""调试用：节点进出各打一行，调式时能看清这一轮走到了哪个节点、走了多久、往哪儿去。

只打标准输出，不动 state、不动控制流，不要了把节点上的 traced(...) 摘掉即可。
**别用花哨符号**：Windows 控制台是 GBK，不在码表里的字符直接 UnicodeEncodeError。
"""
import functools
import inspect
import time

from langgraph.errors import GraphBubbleUp

_PREFIX = "[novel]"


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
