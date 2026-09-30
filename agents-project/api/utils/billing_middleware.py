"""计费中间件：请求入口启动累加器，出口结算扣费。

对 StreamingResponse 在流结束后结算，非流式响应正常结算。
注意：本中间件注册在 auth_middleware 之前（请求入口时 user_id 还未设置），
但全局实际执行顺序为 global → auth → billing → …，所以入站时 user_id 已可用。
"""

import asyncio

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from agents.utils.billing import (
    check_user_credit,
    collect_request_usage,
    settle_billing,
    start_request_billing,
)

# URL 前缀 → service_type 映射
_PATH_TO_SERVICE: dict[str, str] = {
    "/api/novel/": "novel",
    "/api/legal/": "legal",
    "/api/finance/": "finance",
}
_DEFAULT_SERVICE = "chat"


def _detect_service(path: str) -> str:
    for prefix, service in _PATH_TO_SERVICE.items():
        if path.startswith(prefix):
            return service
    return _DEFAULT_SERVICE


async def billing_middleware(request: Request, call_next):
    """计费中间件。

    只对 /agent/ 路径生效（LLM 调用才计费），其余路径直接透传。
    入站：启动累加器，检查用户余额（auth 已执行，user_id 可用）。
          余额为负且无可用套餐时返回 402。
    出站：取 request.state.user_id 判断是否已认证——未认证的请求清空累加器不计费。
          非流式响应立即结算；流式响应把结算延后到流结束后。
    """
    if request.method == "OPTIONS" or "/agent/" not in request.url.path:
        return await call_next(request)

    start_request_billing()

    # 余额预检（此时 auth 已执行，user_id 已设置）
    user_id = getattr(request.state, "user_id", None)
    if user_id is not None:
        allowed, reason = await check_user_credit(user_id)
        if not allowed:
            collect_request_usage()  # 清空累加器
            return JSONResponse(status_code=402, content={"error": reason})

    response = await call_next(request)

    # 出站时 auth 已经执行，取 user_id；未认证不计费
    user_id = getattr(request.state, "user_id", None)

    if user_id is None:
        calls = collect_request_usage()
        return response

    # ── 流式响应：wrap body iterator，流结束后再结算 ──
    # 注：Starlette 1.x 重建的响应类型是 _StreamingResponse，isinstance 不可靠，改用类型名判断
    if "StreamingResponse" in type(response).__name__:
        original = response.body_iterator

        async def _billing_wrapper(it):
            try:
                async for chunk in it:
                    yield chunk
            finally:
                calls = collect_request_usage()
                if calls:
                    asyncio.create_task(
                        settle_billing(
                            user_id=user_id,
                            service_type=_detect_service(request.url.path),
                            calls=calls,
                            request_path=request.url.path,
                        )
                    )

        return StreamingResponse(
            content=_billing_wrapper(original),
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

    # ── 非流式响应：立即结算 ──
    calls = collect_request_usage()
    if calls:
        asyncio.create_task(
            settle_billing(
                user_id=user_id,
                service_type=_detect_service(request.url.path),
                calls=calls,
                request_path=request.url.path,
            )
        )
    return response