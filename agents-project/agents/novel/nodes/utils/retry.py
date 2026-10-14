import asyncio
import inspect


def with_retry_and_fallback(primary, fallback, max_retries=2):
    """把节点包一层重试 + 兜底：抖了就再试几次，实在不行交给 fallback 收尾。

    langgraph 按参数名往形参里注值，包装函数的签名必须留着 state / config / store 这几个名字。
    节点用不到的那几个（比如只读 state 的）不写进自己的签名里，所以按它声明的形参个数喂。
    """
    arity = len(inspect.signature(primary).parameters)

    async def wrapper(state, config=None, store=None):
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                result = primary(*(state, config, store)[:arity])
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    await asyncio.sleep(1)
                    continue
        return fallback(state, last_error)
    return wrapper
