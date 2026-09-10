import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

import redis.asyncio as redis
from psycopg_pool import AsyncConnectionPool

# 独立测试脚本，不经 api.utils.config，自行加载 env（缺省 development）
_root = Path(__file__).resolve().parent.parent
_env_names = [".env.development"]
if os.getenv("APP_ENV", "").strip().lower() in ("production", "prod"):
    _env_names.insert(0, ".env.production")
for _name in _env_names:
    if (_root / _name).exists():
        load_dotenv(_root / _name)
        break

redis_URL = os.getenv("redis_URL", "redis://127.0.0.1:6379/0")
postgreSQL_URL = os.getenv("postgreSQL_URL")
if not postgreSQL_URL:
    raise RuntimeError("缺少 postgreSQL_URL，请在 agents-project/.env.development 中配置")


# 与 api/server.py 同款客户端（连接参数、默认值保持一致）
redis_client = redis.from_url(
    redis_URL,
    max_connections=20,
    socket_timeout=5,
    socket_connect_timeout=5,
    health_check_interval=30,
    decode_responses=True,
)

pg_pool = AsyncConnectionPool(
    conninfo=postgreSQL_URL,
    min_size=1,
    max_size=10,
    timeout=5,
    open=False,
)


async def test_redis():
    try:
        print(f"redis:{redis_URL}" + f"postgresql:{postgreSQL_URL}")
        # 最简单的 ping
        pong = await redis_client.ping()
        print(f"Redis 连接成功: {pong}")

        # 再测试写入和读取
        await redis_client.set("test_key", "hello")
        value = await redis_client.get("test_key")
        print(f"Redis 读写成功: {value}")

        # 清理测试数据
        await redis_client.delete("test_key")

        return True
    except Exception as e:
        print(f"Redis 连接失败: {e}")
        return False


async def test_postgresql():
    try:
        # 打开连接池
        await pg_pool.open()

        # 从池中获取一个连接
        async with pg_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT version()")
                version = await cur.fetchone()
                print(f"PostgreSQL 连接成功: {version[0]}")

        # 关闭连接池
        await pg_pool.close()
        return True
    except Exception as e:
        print(f"PostgreSQL 连接失败: {e}")
        return False


async def main():
    redis_ok = await test_redis()
    pg_ok = await test_postgresql()

    if redis_ok and pg_ok:
        print("\n🎉 所有连接测试通过！")
    else:
        print("\n⚠️ 有连接失败，请检查环境变量和网络。")

if __name__ == "__main__":
    # Python 3.14+ 推荐：用 loop_factory 替代 set_event_loop_policy
    if sys.platform == 'win32':
        asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(main())
