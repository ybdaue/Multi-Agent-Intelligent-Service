"""通用滑动窗口限流（Redis ZSET，真·滑动窗口）。

用法（由粗到细）：
1. global_limit_middleware —— 整个 API 统一闸：所有请求合计每 60s 至多 GLOBAL_LIMIT 次。
   注册到最外层（先于鉴权），未登录的请求也计入，防止被绕过。
2. user_limit_middleware —— 每个登录用户每 60s 至多 PER_USER_LIMIT 次。
   必须在 auth 之后执行才能读到 request.state.user_id（见 server.py 注册顺序）。
3. rate_limit_dependency(prefix, limit, window, per_user=...) —— 依赖工厂，
   供将来为单个接口单独定制（如某个烧钱接口每用户 4 次/分）。
4. sliding_allowed(key, limit, window) —— 底层方法，想自己造 key 时用。

一个窗口内放行 limit 次，达到后返回 429；窗口是滑动的（精确到毫秒），不是固定整点窗口。
Redis 不可用时 fail-open（放行 + 打印告警），避免 Redis 掉线把整个服务锁死。
OPTIONS 预检不计入配额（否则浏览器每次真实请求前的预检会吃掉一半额度）。

接口级定制示例（将来需要时再挂到路由上）：
    @router.post("/query", dependencies=[Depends(rate_limit_dependency("fin/query", 10, per_user=True))])
"""
import secrets
import time

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .db import redis_client

# 默认窗口/阈值（可按需覆盖；整个 API 每用户 20 次/分偏紧，前端轮询频繁可调大）
WINDOW_SECONDS = 60
GLOBAL_LIMIT = 200
PER_USER_LIMIT = 20
_TOO_MANY = "请求过于频繁，请稍后再试"

# 滑动窗口判断与写入在同一个 Lua 脚本里完成，避免“判断-插入”间的竞态。
# 用毫秒时间戳做 score；窗口内每一个放行请求是一条独立记录（member 随机，防同毫秒覆盖）。
# 这里ARGV是用于接收args参数，KEYS接收keys的参数；
# 删掉窗口外的请求，看看窗口内请求数量，超过限制则0，否则加入新记录，设置过期时间
_SLIDING_WINDOW_LUA = """
local now = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window_ms)
if redis.call('ZCARD', KEYS[1]) >= limit then
    return 0
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], window_ms)
return 1
"""
_sliding_script = redis_client.register_script(_SLIDING_WINDOW_LUA)


# 请求放行判断函数
async def sliding_allowed(key: str, limit: int, window: int = WINDOW_SECONDS) -> bool:
    """本次请求是否放行。True 放行；False 表示该窗口内配额已用尽。"""
    now_ms = int(time.time() * 1000)    #毫秒时间戳
    member = f"{now_ms}:{secrets.token_hex(4)}"   #	同一个member只能存在一条记录,8位随机十六进制
    try:
        allowed = await _sliding_script(
            keys=[key],
            args=[str(now_ms), str(window * 1000), str(limit), member],
        )
    except Exception as exc:
        print(f"[rateLimit] Redis 不可用，本次放行（{exc}）")
        return True
    return bool(allowed)



# 全局限流 key 独立于 PER_USER 的桶，避免相互占用
_GLOBAL_KEY = "rl:api:global"

#全局限流函数
async def global_limit_middleware(request: Request, call_next):
    """整个 API 统一限流：所有请求（未登录的也算）共享每 60s GLOBAL_LIMIT 次。"""
    if request.method == "OPTIONS":
        return await call_next(request)
    if not await sliding_allowed(_GLOBAL_KEY, GLOBAL_LIMIT, WINDOW_SECONDS):
        return JSONResponse({"error": _TOO_MANY}, status_code=429)
    return await call_next(request)


#用户限流函数
async def user_limit_middleware(request: Request, call_next):
    """每个登录用户每 60s 至多 PER_USER_LIMIT 次。
    依赖 auth 先执行并写入 request.state.user_id（故需注册在 auth 之后执行，
    Starlette 后注册者先执行，因此它要写在 auth 前面注册）。user_id 缺失时放行
    ——正常情况下不会发生：未登录请求已在上游 auth 中间件以 401 短路。
    """
    if request.method == "OPTIONS":
        return await call_next(request)
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        return await call_next(request)
    if not await sliding_allowed(f"rl:user:u:{user_id}", PER_USER_LIMIT, WINDOW_SECONDS):
        return JSONResponse({"error": _TOO_MANY}, status_code=429)
    return await call_next(request)


#通用限流函数，支持为接口自定限流
def rate_limit_dependency(
    prefix: str,
    limit: int = PER_USER_LIMIT,
    window: int = WINDOW_SECONDS,
    *,
    per_user: bool = False,
):
    """生成一个限流 dependency。
    per_user=True 时按登录用户计数（key 含 user_id，取 request.state.user_id，
    未登录请求退化为 "anon"）；否则为共享单桶（所有调用该依赖的请求共用一个计数）。
    不同接口应使用不同 prefix，互不干扰。
    """
    async def dependency(request: Request):
        if per_user:
            uid = getattr(request.state, "user_id", None)
            key = f"rl:{prefix}:user:{uid if uid is not None else 'anon'}"
        else:
            key = f"rl:{prefix}:global"
        if not await sliding_allowed(key, limit, window):
            raise HTTPException(status_code=429, detail=_TOO_MANY)

    return dependency


# 个人用户限流预设案例：每人每 60s 至多 10 次，共享同一把桶（挂在多个接口上会合计计数）。
# PER_USER = rate_limit_dependency("agent", PER_USER_LIMIT, per_user=True)
