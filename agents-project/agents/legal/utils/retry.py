import asyncio
import inspect


def with_retry_and_fallback(primary, fallback, max_retries=2):
    """Wrap a graph node with retry + fallback on exception.

    wrapper 支持 async primary：节点需要透传 config 以让模型调用走流式回调，
    因此 primary 统一以 (state, config) 调用，fallback 仍以 (state, error) 调用。
    """
    async def wrapper(state, config=None):
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                result = primary(state, config)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    await asyncio.sleep(1)
                    continue
        return fallback(state, last_error)
    return wrapper
