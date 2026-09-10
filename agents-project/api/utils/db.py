"""共享基础设施客户端：Redis（登录态缓存/限流）、PostgreSQL（鉴权/业务数据）。

先导入 config，确保 sys.path 注入与 .env 已加载，连接串才能读到环境变量。
连接均惰性：redis 在发出第一条命令时才建连；pg_pool 由 lifespan 负责打开。
个人开发默认连本机，可用 .env 覆盖（postgreSQL_URL / redis_URL）。
"""
from . import config  # noqa: F401  保证环境变量就绪（重复导入 config 是无害 no-op）

import os

import redis.asyncio as redis
from psycopg_pool import AsyncConnectionPool

redis_URL = os.getenv("redis_URL", "redis://127.0.0.1:6379/0")
postgreSQL_URL = os.getenv("postgreSQL_URL")
if not postgreSQL_URL:
    raise RuntimeError(
        "缺少 postgreSQL_URL，请在 agents-project/.env.development 或部署环境中配置"
    )

redis_client = redis.from_url(
    redis_URL,
    max_connections=20,
    socket_timeout=5,
    socket_connect_timeout=5,
    health_check_interval=30,
    decode_responses=True,  # 返回 str 而非 bytes，便于个人开发调试；正式要原始类型可去掉
)

pg_pool = AsyncConnectionPool(
    conninfo=postgreSQL_URL,
    min_size=1,
    max_size=10,
    timeout=5,
    open=False,  # 惰性：由 server lifespan 里 await pg_pool.open() 打开，导入时不需事件循环
)
