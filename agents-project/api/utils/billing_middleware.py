"""计费中间件：创建 TokenCollectorHandler 注入请求上下文，出口结算扣费。

LangGraph 会通过 config.callbacks 把 handler 传播到所有子图和内部 Task，
不受 asyncio Task 隔离影响，因此能捕获全部 LLM 调用的 token。

对 StreamingResponse 在流结束后结算，非流式响应正常结算。
"""
import asyncio

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from agents.utils.billing import (
    TokenCollectorHandler,
    check_user_credit,
    settle_billing,
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
    入站：创建 TokenCollectorHandler，检查用户余额。
          余额为负且无可用套餐时返回 402。
    出站：取 request.state.user_id 判断是否已认证——未认证请求不计费。
          非流式响应立即结算；流式响应把结算延后到流结束后。
    """
    if request.method == "OPTIONS" or ("/agent/" not in request.url.path and "/setup/" not in request.url.path):
        return await call_next(request)

    # 创建 TokenCollectorHandler，端点将其注入 LangGraph config.callbacks
    handler = TokenCollectorHandler()
    request.state.token_collector = handler

    # 余额预检（此时 auth 已执行，user_id 已设置）
    user_id = getattr(request.state, "user_id", None)
    if user_id is not None:
        allowed, reason = await check_user_credit(user_id)
        if not allowed:
            return JSONResponse(status_code=402, content={"error": reason})

    response = await call_next(request)

    # 出站时 auth 已经执行，取 user_id；未认证不计费
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        return response

    # ── 流式响应：wrap body iterator，流结束后 handler 已收集完整 token ──
    if "StreamingResponse" in type(response).__name__:
        original = response.body_iterator

        async def _billing_wrapper(it):
            try:
                async for chunk in it:
                    yield chunk
            finally:
                calls = handler.get_calls()
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
    calls = handler.get_calls()
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