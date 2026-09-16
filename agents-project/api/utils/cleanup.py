"""过期数据定时清理：向量库切片 + PG temp_file/created_file 行。

由 server lifespan 起一个后台任务周期执行，独立于用户请求触发。
"""

import asyncio
import time

from agents.utils.executor import RAG_IO_EXECUTOR, run_in_pool
from agents.utils.RAG import FILE_TTL_SECONDS, delete_expired_chunks

from .db import pg_pool

CLEANUP_INTERVAL = 60 * 60        # 每小时扫一次
CLEANUP_INITIAL_DELAY = 5 * 60    # 启动后 5 分钟首跑，避开冷启动


async def sweep_once() -> None:
    """执行一轮清理。各步骤独立 try/except，绝不向上抛异常。"""
    # 1) 向量库：只清 legal_docs（用户上传切片）；laws_docs 是系统法条，不参与 TTL
    try:
        n = await run_in_pool(
            RAG_IO_EXECUTOR, delete_expired_chunks, time.time() - FILE_TTL_SECONDS
        )
        if n:
            print(f"[cleanup] 清理过期切片 {n} 条")
    except Exception as e:
        print(f"[cleanup] 向量库清理失败（忽略，下轮重试）: {e}")

    # 2) PG：temp_file / created_file 行级过期清理
    try:
        async with pg_pool.connection() as conn:
            await conn.execute('DELETE FROM temp_file WHERE "expiresAt" < now()')
            await conn.execute('DELETE FROM created_file WHERE "expiresAt" < now()')
            await conn.commit()
    except Exception as e:
        print(f"[cleanup] 数据库清理失败（忽略，下轮重试）: {e}")


async def cleanup_loop() -> None:
    """后台循环：延迟首跑，然后按间隔执行，直到被取消。"""
    await asyncio.sleep(CLEANUP_INITIAL_DELAY)
    while True:
        await sweep_once()
        await asyncio.sleep(CLEANUP_INTERVAL)
