# 必须先导入 config：它负责 sys.path 注入与 .env 加载。
# 后续 import agents 及其模块级建模型（需 DEEPSEEK_API_KEY）依赖此顺序。
from .utils import config

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.utils import RAG
from agents.utils.mcp_client import close_mcp, refresh_mcp_tools

from .utils.auth import auth_middleware
from .utils.cleanup import cleanup_loop
from .utils.db import pg_pool
from .utils.rateLimit import global_limit_middleware, user_limit_middleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:  # 启动时：尝试初始化 RAG，失败不阻塞
        RAG.init()
    except Exception:
        pass
    try:
        await pg_pool.open()
    except Exception as exc:
        print(f"[server] PostgreSQL 未就绪，连接池延后打开（{exc}）")
    try:  # 启动时：接入外部 MCP 工具（未配置 MCP_SERVERS 则空转）
        await refresh_mcp_tools()
    except Exception as exc:
        print(f"[server] 外部 MCP 工具未接入（{exc}）")
    cleanup_task = asyncio.create_task(cleanup_loop(), name="ttl-cleanup")
    # 不 await：首拉在专属线程池里进行，服务不等它就开始接收请求（这段时间
    # /latest 返空、/query 返 503「数据正在初始化」）。是否持续刷新由
    # finance.method.ENABLE_PERIODIC_FETCH 控制。
    finance_task = asyncio.create_task(finance_updater_loop(), name="finance-updater")
    try:
        yield
    finally:
        # 关闭时：先停后台任务，再断开 MCP 连接（Chroma 客户端自动断开）
        for task in (cleanup_task, finance_task):
            task.cancel()
        for task in (cleanup_task, finance_task):
            try:
                await task
            except asyncio.CancelledError:
                pass
        shutdown_finance_executor()
        await close_mcp()
        await pg_pool.close()


app = FastAPI(title="智能体 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 中间件按“后注册者先执行”排列。注册顺序 与 实际执行顺序（先后）：
#   注册：CORS -> user_limit -> auth -> global
#   执行：global -> auth -> user_limit -> CORS
# - global 最外层：整 API 合计 200 次/60s，未登录请求也计入，防止绕过。
# - auth 其次：校验登录并写 request.state.user_id。
# - user_limit 要能读到 user_id，必须排在 auth 之后执行（故注册在 auth 之前）：每人 10 次/60s。
# - CORS 最内层：给所有响应补 CORS 头。
# Redis/PostgreSQL 客户端与鉴权逻辑见 api/auth.py 与 api/db.py；限流见 api/rateLimit.py。
app.middleware("http")(user_limit_middleware)
app.middleware("http")(auth_middleware)
app.middleware("http")(global_limit_middleware)

# 各功能域路由：finance / legal / novel 各自独立成模块
from .finance.agent import router as finance_agent_router
# 后台行情循环在 lifespan 里才被调用，此处导入即够（名字在运行时解析）
from .finance.method import (
    finance_updater_loop,
    router as finance_method_router,
    shutdown_finance_executor,
)
from .legal.method import router as legal_method_router
from .legal.agent import router as legal_agent_router
from .novel.agent import router as novel_agent_router
# 开书：独立成图、独立 checkpoint 名，只在「新建小说」弹窗里用
from .novel.setup import router as novel_setup_router
# 小说侧的只读查询口：这一章的台账、这本书的改动清单
from .novel.method import router as novel_method_router

app.include_router(finance_agent_router)
app.include_router(finance_method_router)
app.include_router(legal_method_router)
app.include_router(legal_agent_router)
app.include_router(novel_agent_router)
app.include_router(novel_setup_router)
app.include_router(novel_method_router)
