"""SSE 心跳：给"长时间不吐字"的异步流垫上周期性的字节。

为什么需要：开书（api/novel/setup.py）与写章（api/novel/agent.py）两条 SSE，图里有些节点不
流式（maintain 提取、intension 判意图这类），会闷住几十秒甚至几分钟，期间这条连接一个字节都
不发。生产链路上 nginx 的 proxy_read_timeout 只看"有没有数据"，静默超过默认的 60s 就认定连接
死了、直接掐断 —— 前端表现为兜底的"无法连接 AI 服务"，后端则被 cancel；而 CancelledError 不是
Exception，两侧的 except 都不接，于是既没有 error 事件也没有 traceback，日志断在最后一个节点
结束处（曾经是 maintain 跑 178.7s 那一轮）。

心跳把这些"空闲"变成"每隔十几秒有一行"，任何代理的读超时都碰不到。发的是 SSE 注释行（以 ":"
开头），按协议客户端一律忽略 —— 前端 eventsource-parser 不用改。
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TypeVar

T = TypeVar("T")

# 心跳间隔：远小于常见代理的读超时（nginx 默认 60s），留足余量。
HEARTBEAT_INTERVAL = 15.0

# SSE 注释行：以 ":" 开头，客户端忽略，但它是真实字节，足以刷新代理的读超时。
HEARTBEAT = ": keep-alive\n\n"


class _Done:
    """哨兵：源流正常结束。"""


_DONE = _Done()


async def with_heartbeat(
    source: AsyncIterator[T], interval: float = HEARTBEAT_INTERVAL
) -> AsyncIterator[T | None]:
    """给 source 包一层心跳：每静默 interval 秒 yield 一个 None（表示"该发一行注释了"）。

    源流由后台 task 拉取、灌进队列，消费端带超时地取：
      - 取到事件   → 原样 yield；
      - 取超时     → yield None，调用方据此发一行心跳；
      - 源流结束   → 消费端 return；
      - 源流抛异常 → 在消费端原样重抛（保持原来的错误语义，外层 except 照旧接得住）；
      - 消费端被取消（客户端断开）→ finally 里把后台 task 也取消，图随之停下。
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def pump() -> None:
        try:
            async for item in source:
                queue.put_nowait(item)
        except asyncio.CancelledError:
            raise  # 消费端已经走了，不必回话
        except BaseException as exc:  # noqa: BLE001 —— 原样交给消费端重抛
            queue.put_nowait(exc)
        else:
            queue.put_nowait(_DONE)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                yield None
                continue
            if item is _DONE:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        task.cancel()