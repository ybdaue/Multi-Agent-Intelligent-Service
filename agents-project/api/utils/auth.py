"""登录态校验：从 Authorization 头解析 Bearer token，换算成 userId。

策略：Redis 缓存优先（decode_responses=True 所以取到的是 str）；
命中时滑动续期（续 1h），活跃用户 Redis 不过期；
未命中回退 PostgreSQL 查 Session 表，有效会话会把 token→userId
按剩余时间（封顶 2h）写回缓存。
"""
from datetime import datetime, timezone

from fastapi import Request
from fastapi.responses import JSONResponse

from .db import pg_pool, redis_client

_UNAUTHORIZED = JSONResponse(
    {"error": "未登录或登录已过期，请重新登录"}, status_code=401
)


def session_remaining_seconds(expires_at: datetime) -> int:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    expires_at_utc = expires_at.astimezone(timezone.utc)
    return int((expires_at_utc - datetime.now(timezone.utc)).total_seconds())


async def resolve_user_id(token: str):
    """返回 token 对应的 userId；token 无效/过期/查询出错时返回 None。"""
    user_id = None
    try:
        user_id = await redis_client.get(token)
    except Exception:
        pass
    if user_id is not None:
        # 缓存命中 → 滑动续期，活跃用户 Redis 不过期
        try:
            await redis_client.expire(token, 3600)
        except Exception:
            pass
        return user_id

    try:
        async with pg_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT "userId", "expiresAt" FROM "Session" WHERE "token" = %s',
                    (token,),
                )
                row = await cur.fetchone()
    except Exception:
        return None

    if row is None:
        return None

    id_, expires_at = row
    remain = session_remaining_seconds(expires_at)
    if remain <= 0:
        return None
    user_id = id_
    try:
        # 按剩余时间缓存，封顶 2h（session 最大生命周期）
        await redis_client.set(token, user_id, ex=max(1, min(remain, 7200)))
    except Exception:
        pass
    return user_id


async def auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    # 健康检查 / docs / openapi 不校验登录
    path = request.url.path
    if path in ("/health", "/docs", "/openapi.json"):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return _UNAUTHORIZED

    token = auth_header[len("Bearer ") :].strip()

    user_id = await resolve_user_id(token)
    if user_id is None:
        return _UNAUTHORIZED
    request.state.user_id = user_id

    # 异步记录今日活跃 & 最后活跃时间（不阻塞响应）
    try:
        async with pg_pool.connection() as conn:
            await conn.execute(
                """INSERT INTO "UserActivityLog" ("id", "userId", "date")
                   SELECT gen_random_uuid()::text, %s, CURRENT_DATE
                   WHERE NOT EXISTS (
                       SELECT 1 FROM "UserActivityLog"
                       WHERE "userId" = %s AND "date" = CURRENT_DATE
                   )""",
                (user_id, user_id),
            )
            await conn.execute(
                'UPDATE "User" SET "lastActiveAt" = NOW() WHERE "id" = %s',
                (user_id,),
            )
    except Exception:
        pass  # 非关键功能，忽略错误

    return await call_next(request)
