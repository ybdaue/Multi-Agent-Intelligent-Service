# 必须先导入 config：它负责 sys.path 注入与 .env 加载。
# 后续 import agents 及其模块级建模型（需 DEEPSEEK_API_KEY）依赖此顺序。
from .utils import config

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.utils import RAG

from .utils.auth import auth_middleware
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
    yield  # 关闭时：无额外清理（Chroma 客户端自动断开）
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

# 各功能域路由：finance / legal 各自独立成模块
from .finance.agent import router as finance_agent_router
from .finance.method import router as finance_method_router
from .legal.method import router as legal_method_router
from .legal.agent import router as legal_agent_router

app.include_router(finance_agent_router)
app.include_router(finance_method_router)
app.include_router(legal_method_router)
app.include_router(legal_agent_router)
