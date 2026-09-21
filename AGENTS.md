# AGENTS.md — 项目知识库

我叫小杨，在做一个 **AI 智能服务项目**。仓库根目录 `E:\html\nextjs` 下有两个子项目：

- **agents-project**（Python）— agent 后端（智能体调度 + RAG + 法律/金融能力 + A股数据）
- **my-app**（Next.js）— 前端 Web 应用（登录、服务大厅、法律咨询、股票行情/图表）

当前 git 分支：`main`（基线提交 `version:1.0`）。`.env` 一律不入库。

> 本文档最后核对：**2026-09-10**。上一版描述的 `agents/RAG.py`、`agents/parse.py`、
> `agents/legal_analyzer/`、`api/finance/method_router.py`、`.env.example`、`/health` 路由
> **均已不存在**——已重构为 `agents/utils/*`、`agents/legal/subagents/*`、
> `api/<domain>/{agent,method}.py`、`.env.development` / `.env.production`。

---

## 一、整体架构与调用链

```
浏览器 (my-app, :3000)
  └─ src/proxy.ts 全局登录守卫（Next 16 的 middleware 新名）
       └─ Next Route Handler 做 BFF：鉴权 → 带 Bearer 转发后端 → SSE 透传
            ├─ /api/legal/askAgent   → 后端 POST /api/legal/agent/legalAgent (multipart, SSE)
            ├─ /api/legal/download   → 后端 GET  /api/legal/method/download/{fileId}
            ├─ /api/legal/sessions[/history] → 后端 GET /api/legal/method/sessions[/history]
            ├─ /api/finance/agent    → 后端 POST /api/finance/agent/stream (SSE)
            ├─ /api/finance/stockList|tickChart → 后端 GET /api/finance/method/{latest,tick}
            ├─ /api/chat             → AI SDK 直连 DeepSeek（通用闲聊，不进后端 agent）
            └─ /api/func             → 服务大厅卡片列表（Next 本地静态返回）
后端 (agents-project, :8080, FastAPI)
  ├─ 中间件：global 限流 → auth 鉴权 → user 限流 → CORS
  ├─ 智能体注册表 agents/__init__.py: {"finance", "multiAgent", "legalAgent"}
  ├─ legalAgent：LangGraph 图（checkin→preprocessing→Intent→load_memory→assistant⇄child_agent→summary→update）
  ├─ multiAgent：任务路由器（LLM 意图路由 → use_legal_agent / use_finance_agent）
  └─ finance：FinanceAgent 类（LangGraph + tool_registry 行情工具）
基础设施 (Docker / 本机)
  ├─ PostgreSQL:5432  my-app 的 Prisma 库（Session / checkpoint / agent_store / user_session / legal_bm25 / legal_laws …）
  ├─ Chroma:8000      向量库（legal_docs 用户上传 / laws_docs 法规）
  └─ Redis:6379       登录态缓存 + 限流计数
本地 embedding 模型：agents-project/models/bge-large-zh-v1.5（离线加载，gitignore）
```

**端口别混**：后端 FastAPI 是 **8080**（`NEXT_PUBLIC_API_URL` 默认即它），Chroma 才是 **8000**。
（上一版 AGENTS.md 把后端也写成 8000，是错的。）

---

## 二、agents-project（Python 后端）

技术栈：Python 3.12（`.venv`）、FastAPI、LangChain、LangGraph(>=1.2.11)、chromadb、
sentence-transformers、rank-bm25、jieba、akshare、tickflow、psycopg[binary,pool]、redis、
python-docx、pdfplumber、openpyxl/xlrd、python-multipart。
依赖清单：`requirements.txt`（唯一权威；`pyproject.toml` 历史遗留、字段不全）。

### 启动与常用命令
```bash
cd agents-project
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 环境变量（config.py 只认这两个文件，都是 gitignore 的，没有 .env / .env.example）：
#   未设 APP_ENV           → .env.development
#   APP_ENV=production/prod → .env.production 优先，回退 .env.development
# 变量名：DEEPSEEK_API_KEY / OPENAI_API_KEY / ZHIPU_API_KEY / DASHSCOPE_API_KEY /
#        SILICONFLOW_API_KEY / postgreSQL_URL / redis_URL
# 可选：MCP_SERVERS（JSON，接入外部 MCP Server；不设则一个都不接，见 agents/utils/mcp_client.py）
uvicorn api.server:app --reload --host 0.0.0.0 --port 8080
# 前置依赖：Docker 里跑 Chroma(host=localhost:8000)、Redis、PostgreSQL；
#          本地 embedding 模型在 models/bge-large-zh-v1.5（缺失则 RAG 静默不可用）

# 导入法规（父子切分：子→Chroma laws_docs + PG legal_bm25；父→PG legal_laws）
python agents/utils/legal_ingest.py                 # 幂等，已导入文件自动跳过
python agents/utils/legal_ingest.py --force --batch 10
python agents/utils/legal_ingest.py --sync          # 仅把 Chroma laws_docs 重同步到 legal_bm25 表
```

### 目录结构

| 路径 | 说明 |
|---|---|
| `api/server.py` | FastAPI 入口：lifespan(开 PG 连接池 + 尝试 RAG.init)、挂 4 个 router、装配中间件。**无任何 `@app.get` 路由**（/health 已移除） |
| `api/utils/config.py` | 注入 sys.path + 按 APP_ENV 选 `.env.development` / `.env.production` |
| `api/utils/db.py` | `redis_client`（redis.asyncio，decode_responses）+ `pg_pool`（AsyncConnectionPool，惰性 open） |
| `api/utils/auth.py` | `auth_middleware`：Bearer token → userId（better-auth 的 cuid），写 `request.state.user_id`。Redis 优先，未命中查 PG `"Session"` 表，有效则按剩余时长（封顶 600s）写回 Redis |
| `api/utils/rateLimit.py` | Redis ZSET + 单 Lua 脚本原子滑动窗口；`global_limit_middleware`(200/60s，含未登录) / `user_limit_middleware`(20/60s 每用户) / `rate_limit_dependency()` 工厂 |
| `api/utils/sessions.py` | 读 `user_session` / `user_session_history`（列表分页、单会话历史） |
| `api/finance/agent.py` | `/api/finance/agent`：`POST /query`(非流式) + `POST /stream`(SSE，**裸 `data:{token\|thread_id\|done\|error}`，与 legal 侧协议不同**) |
| `api/finance/method.py` | `/api/finance/method`：`GET /latest`(全市场分页/搜索/排序)、`/query`、`/tick`(分时，30s 缓存)。数据源 akshare，含交易日历懒加载 |
| `api/legal/agent.py` | `/api/legal/agent`：`POST /multiAgent` 与 `POST /legalAgent`（都是 multipart + SSE），共用 `_stream_agent`；上传文件落 `temp_file`(7天)，state 里只放行 id，**字节不进 state** |
| `api/legal/method.py` | `/api/legal/method`：`GET /sessions`、`/sessions/history`、`/download/{fileId}`（查 `legal_created_file` 表，按 `request.state.user_id` 鉴权） |
| `agents/__init__.py` | 注册表 `_AGENTS = {finance: FinanceAgent, multiAgent, legalAgent}`；`get_agent(name)` 单例化 |
| `agents/multiAgent.py` | 任务路由器：SystemMessage 路由提示词 + DeepSeek `bind_tools`；工具 `use_legal_agent` / `use_finance_agent`（**后者仅占位回复"暂未开通"**）；对 legal 工具 JSON 结果做清洗防回显；`BoundedMemorySaver` 检查点 |
| `agents/finance/agent.py` | `FinanceAgent` 类：date_injector → assistant ⇄ tools，MAX_STEPS=10；同步 `run()` + 异步 `stream()`；`BoundedMemorySaver` |
| `agents/finance/saver.py` | finance 版 BoundedMemorySaver |
| `agents/utils/RAG.py` | Chroma 封装：`legal_docs`(用户上传, TTL 3天) / `laws_docs`(法规)；`upsert_chunks` `retrieve_text`(向量) `retrieve_chunk`(批量) `expand_to_parents`(子→父) `delete_expired_chunks`；embedding=bge-large-zh-v1.5。**host/port 硬编码 `localhost:8000`** |
| `agents/utils/parse.py` | 文件解析 + 切片：txt/md/json/csv/xml/html/pdf/docx/doc/xlsx/xls；`DEFAULT_CHUNK_SIZE=700`、`DEFAULT_OVERLAP=150` |
| `agents/utils/legal_ingest.py` | 法规导入 CLI（见上）；父子切分 + 幂等 + `--sync` 同步 BM25 |
| `agents/utils/bm25_index.py` | 从 PG `legal_bm25` 表懒加载 `BM25Okapi` 内存索引（jieba 分词，缺失则逐字降级）；`_init_lock` 防冷启动并发重复建索引 |
| `agents/utils/law_parent_store.py` | PG `legal_laws` 父表读写：`upsert_parents` / `get_parents` / `delete_file` |
| `agents/utils/checkpoint.py` | `create_checkpoint(agent_name)` → PostgresCheckpointSaver，落 `checkpoint` 表；行按 (userId, agentName, threadId, **checkpointNs**, checkpointId) 定位，ns 必须参与读写（子图快照与父图各存各的）；每 thread 保留最近 `MAX_SNAPSHOTS=5` 个**根图层**快照及其之后的全部子图快照（超限同事务删旧）；serde=msgpack+base64 存 jsonb |
| `agents/utils/agent_store.py` | `create_agent_store(agent_name)` → PostgresStore（LangGraph BaseStore），落 `agent_store` 表；**userId 约定取 namespace 末位**；未实现 ListNamespacesOp |
| `agents/utils/boundMemory.py` | `BoundedMemorySaver(max_threads=10)` LRU 检查点，防长驻 OOM。现仅 multiAgent / finance 用（legal 已换 PG） |
| `agents/utils/models.py` | `create_chat_model(provider, model, ...)`（openai/deepseek/zhipu|glm/qwen/guiji）；`MainModel` / `IntentModel` / `CompressModel`；`RerankModel(query, docs, top_n)` 直连 SiliconFlow `/v1/rerank`（bge-reranker-v2-m3）。当前 MainModel 走硅基流动 `deepseek-ai/DeepSeek-V4-Flash` |
| `agents/legal/__init__.py` | **法律子 Agent 主图**（~970 行）：见下方"图结构" |
| `agents/legal/memory.py` | `checkin`(图首落库本轮提问) / `load_memory`(读画像+摘要) / `update`(会话持久化 + 画像更新 + 摘要压缩)；直接 psycopg 同步连接 |
| `agents/legal/subagents/analysize.py` | `analyze_document` 工具：分页取切片 → `retrieve_chunk` 批量 top5 法条 → 分批判险 → 归并去重 |
| `agents/legal/subagents/consultor.py` | `consultor` 工具：`create_agent` + `retrieve_law_basis`，强制先检索后作答 |
| `agents/legal/subagents/draftor.py` | `draft_document_agent` 工具：LLM 生成 → python-docx → 字节写入 PG `legal_created_file`（返回 file_id + filename，不落盘） |
| `agents/legal/tools/retrieve_law.py` | **法条检索唯一出口**：向量(Chroma) + BM25(PG) → RRF 融合 → 交叉编码器重排 → 子命中展开为父模块整段 |
| `tool_registry/` | LangChain 工具注册表：`__init__.py` 的 `register(category, tool)` / `get_tools(category)`；`ak.py` 提供 `get_a_stock_price`（6位代码 → 6→.SH / 0,3→.SZ），注册在 `"finance"` 类目；`postgres.py` / `chroma.py` 提供只读查询与语义检索，注册在 `"database"` 类目。**原名 `mcp/`，因遮蔽官方 `mcp` SDK 而改名**。`get_tools(category)` = 本地注册 + 外部 MCP 工具合并 |
| `mcp_server/` | **对外提供**的 MCP Server（官方 `mcp` SDK，v2 的 `MCPServer`，`from mcp.server.mcpserver import MCPServer`）：`server.py` 建实例 + `lifespan` 生命周期；`postgres_tools.py` / `chroma_tools.py` 用 `@mcp.tool(...)` 注册并带 `ToolAnnotations`（只读/幂等/无副作用）。入口 `python -m mcp_server`（传输暂用 SDK 默认 stdio）。工具实现直接复用 `tool_registry` 的纯函数，两处共用一份逻辑 |
| `agents/utils/mcp_client.py` | **消费外部** MCP 的通用客户端（与 `mcp_server/` 方向相反）：`refresh_mcp_tools()` 启动时连接 + 拉工具 + 缓存，`get_mcp_tools(category)` 同步取用，`close_mcp()` 断开。外部工具被包成 LangChain `StructuredTool`（名加 `服务名__` 前缀防重名），agent 侧 `bind_tools` 用法不变。配置读环境变量 `MCP_SERVERS`（JSON，`command`→stdio / `url`→streamable-http，`category` 决定并入哪个类目，默认 `"mcp"`）；单个 server 连不上只跳过（失败隔离）。⚠️ 外部工具返回值不可信，注意提示注入 |
| `middleware/date_injector.py` | `inject_current_date`：给金融助手系统提示注入"今天是 X" |
| `test/` | `run_laws_pipeline.py`(端到端验证父子切分→检索→父返回，跑完自动清理 `sample_law_001` 数据)、`test_connections.py`、`test_rerank_model.py` |

### ⚠️ 未被引用的脚本（保留，勿当生效代码改）

`agents/legal/tools/` 下这 5 个模块**没有任何模块 import 它们**（`flk_npc_client.py` 只被同样无人引用的
`law_search_engine.py` 引用），合计约 2600 行：

- `damage_calculator.py`（878 行）
- `generate_complaint_docx.py`（428 行）
- `law_search_engine.py`（665 行）
- `limitation_calculator.py`（682 行）
- `flk_npc_client.py`（702 行）

它们是按"skill 资源"有意留下的思考/模板/代码素材，**不是** legal agent 的运行路径。
改检索逻辑请认准 `agents/legal/tools/retrieve_law.py`。

另：`agents-project/tools/` 与 `agents-project/skills/` 两个目录**当前为空**。

### legal_agent 图结构（`agents/legal/__init__.py`）

```
START → checkin → preprocessing → Intent → load_memory → assistant ⇄ child_agent
                                                              ↓ (无 tool_calls)
                                                           summary → update → END
```

- `checkin`：**图首**就把本轮提问 + 会话行落库，保证后续解析失败/意图兜底/流被中断也不丢会话。
- `preprocessing`：TTL 惰性清扫 → 内容哈希查重（命中即复用）→ `parse_and_chunk` → `upsert_chunks`；
  解析/写库失败用 `Command(goto=END)` 提前退出。
- `Intent`：`IntentModel` 输出严格 JSON（primary_intent ∈ draft/analyze/consult/chat + pending_tasks + task_context），
  解析失败走 `rule_based_fallback`。`disable_streaming=True`（意图 JSON 不进 SSE）。
- `assistant`：任务栈调度。无 `pending_tasks` → 走 `_casual_answer` 轻量直答（不绑工具）；
  否则按 `decision_prompt` 每轮**强制只调一个工具**（多余 tool_calls 丢弃）；重复执行已完成任务则 `step += 2` 加速触顶。
- 硬停止：`step >= max_step(10)` 或任务栈耗尽 → 直接产终稿，不再调模型。
- `summary`：仅当 config 里 `produce_summary=True`（即直连 `legalAgent`）才用 `CompressModel` 生成 200~600 字终稿，
  并 `RemoveMessage` 替换掉 assistant 的简短终稿避免重复；multiAgent 以子图方式调用时不总结。
- 记忆三件套：`checkpoint` 表(Postgres 快照) + `agent_store` 表(用户画像) + `user_session*` 表(会话历史)。
  摘要压缩在 `memory.update`：保留最近 `RECENT_ROUNDS=5` 轮完整消息，更早折叠进 `summary`。

### 关键约定（改代码前必读）

- 所有对话智能体以 **DeepSeek 系模型为主模型**；法律子智能体内部温度 0.1~0.3。
- legal SSE 事件：`session`(回传权威 threadId) / `token` / `file_generated` / `done` / `error`。
  **finance 的 `/stream` 是另一套协议**（裸 data，无 event 名）。
- 上传文件：`file_id = md5(内容)`，同内容重复上传靠 Chroma upsert 原地覆盖去重；
  同会话(userId+threadId)同 hash 在 `temp_file` 走唯一键复用行。
- 用户上传切片 TTL=3 天（`FILE_TTL_SECONDS`）。
- `threadId` 自带归属：格式 `{userId}:{uuid}`，新会话由后端生成并经首个 SSE `session` 事件回传，
  前端沿用；客户端传回的一律校验前缀，不匹配即 403（归属是结构性的，不依赖每条 SQL 都记得带 userId 过滤）。
- `analysis_result` / `answer_result` / `output_file` 是**本轮产物**：`update` 节点轮末统一清空
  （`memory.py` 的 `_clear_artifacts`），不要在跨轮逻辑里依赖它们（要跨轮的信息写进 `summary`）。
- `download` 按 `fileId` 查 `legal_created_file` 表（限定同一 userId），agent 产物不落盘。
- Redis 挂掉时：鉴权失败（查不到 token → 401）；**限流 fail-open 放行**。二者行为不一致，是刻意的。

---

## 三、my-app（Next.js 前端）

技术栈：Next.js 16.1.6（App Router, React 19.2.3）、TypeScript、SCSS Modules、
Prisma 7（@prisma/adapter-pg）、better-auth 1.6、AI SDK v6（@ai-sdk/deepseek）、
eventsource-parser、next-themes、zod；部署 Vercel（`vercel.json`）。
客户端 SDK 生成为 `src/generated/prisma`。

### 常用命令
```bash
cd my-app
npm install
npm run dev        # = prisma generate && next dev -p 3000
npm run build / npm run lint
npx prisma generate
```

### 页面路由（App Router）

| 路由 | 说明 |
|---|---|
| `/` | 重定向到 /home |
| `/login` | better-auth 登录页（`disableSignUp`，账号手动入库）；已登录访问会跳 /home |
| `/terms`、`/privacy` | 公开条款页（`src/components/legal-page.tsx` 复用组件） |
| `/home` | 服务大厅：卡片数据来自 `src/lib/server/home/services-data.ts`（与 `/api/func` 里的列表**重复维护**） |
| `/home/legal` | **AI 法律助手**：会话侧栏(服务端分页) + 聊天 + 文件上传 + SSE 流式 |
| `/home/content` | AI 对话(可用) / 图片(disabled) / 视频(disabled) |
| `/home/finance` | 金融首页（layout + 左右侧栏） |
| `/home/finance/stock` | A股列表：搜索/排序/分页 + 右下角 AI 股票对话浮窗 |
| `/home/finance/[id]/detail` | 个股详情：报价 + K线/分时/成交量 + BOLL/MACD/KDJ/RSI 自绘指标图 + AiAnalysisPanel |
| `/home/reports`、`/home/help` | 占位页 |

### API 路由（BFF）

| 路由 | 转发目标 |
|---|---|
| `/api/auth/[...all]` | better-auth（`src/proxy.ts` 对其放行） |
| `/api/chat` | AI SDK `streamText` 直连 DeepSeek（通用闲聊，**不经**后端 agent） |
| `/api/legal/askAgent` | 后端 `POST /api/legal/agent/legalAgent`，multipart + SSE 原样透传 |
| `/api/legal/download` | 后端 `GET /api/legal/method/download/{fileId}` |
| `/api/legal/sessions` | 后端 `GET /api/legal/method/sessions` |
| `/api/legal/sessions/history` | 后端 `GET /api/legal/method/sessions/history` |
| `/api/finance/agent` | 后端 `POST /api/finance/agent/stream`，SSE 透传 |
| `/api/finance/stockList` | 后端 `GET /api/finance/method/latest` |
| `/api/finance/tickChart` | 后端 `GET /api/finance/method/tick` |
| `/api/func` | Next 本地静态返回服务卡片列表 |

### 关键模块

- `src/proxy.ts`：**Next 16 的 middleware（文件已改名 proxy）**。`/api/auth` 放行；
  `PUBLIC_PATHS = ["/login","/terms","/privacy"]`；未登录跳 /login，已登录访问 /login 跳 /home。
  **注意 matcher 覆盖了 `/api/*`**：未登录调 `/api/chat`、`/api/func` 会拿到 302 跳 HTML 登录页，
  而不是 401 JSON（BFF 路由自身另有 `withAuth` 兜底）。
- `src/lib/auth.ts`：better-auth。`emailAndPassword.disableSignUp=true`；session `expiresIn=2h`、
  `updateAge=0`、`disableSessionRefresh=false`（即每个请求都续期）。Prisma adapter，
  baseURL=`NEXT_PUBLIC_BETTER_AUTH_URL`。
- `src/lib/server/get-session-auth.ts`：取 better-auth 会话并**从 cookie 里切出数据库 `Session.token`**
  （cookie 形如 `rawToken.signature`），作为 Bearer 交给 BFF 转发给后端做 Redis 校验。
  这是前端 → 后端鉴权的唯一桥 —— userId 不再经前端传递，由后端从该 token 反查。
- `src/lib/utils/with-auth.ts`：BFF 路由包装器，未登录直接 401 JSON。
- `src/lib/env.ts`：zod 校验 `DATABASE_URL`(必填)、`NEXT_PUBLIC_BETTER_AUTH_URL`、`NEXT_PUBLIC_API_URL`、
  `APIKEY`(可选)、`TICKFLOW_KEY`(必填)。
- `src/lib/fetch.ts`：`request`/`requestJSON`，带超时(默认 10s；流式传 `timeout: 0`)与错误归类。
- `src/app/home/legal/components/LegalChat/index.tsx`：法律对话总控——会话列表分页/触底加载、
  历史拉取(带 `historySeqRef` 使过期请求失效)、SSE 解析(session/token/file_generated/done/error)、
  `AbortController` 中断、发送后刷新列表。
- `src/app/services/stream-chat.ts`：**finance 侧**的 SSE 解析（裸 data.token/thread_id/done/error），
  与 legal 侧的解析逻辑不共用。
- 股票行情双源：列表/分时走后端 akshare(`/api/finance/method/*`)，报价/K线走 tickflow API(带 x-api-key)。

### 环境变量（`.env*` 均 gitignore）
`DATABASE_URL`、`NEXT_PUBLIC_BETTER_AUTH_URL`、`NEXT_PUBLIC_API_URL`（兜底 `http://localhost:8080`）、
`APIKEY`(DeepSeek)、`TICKFLOW_KEY`。

---

## 四、跨项目协作要点（高频坑）

1. **userId = better-auth 的 cuid，由后端自己从 token 解析**：前端**不再传** userId，
   BFF 只带 `Authorization: Bearer <sessionToken>`。后端 `auth_middleware` 把它换成 cuid
   写进 `request.state.user_id`，端点一律从这里取（`api/legal/agent.py`、`api/legal/method.py`）。
   它同时是 `checkpoint` / `agent_store` / `user_session` / `temp_file` / `novel` 的隔离 key，
   且**就是真实主键** —— 这几张表都有 `ON DELETE CASCADE` 外键指向 `User.id`，注销用户会连带清空。
2. **端口**：后端 API `8080`，Chroma `8000`。后端默认连 Chroma `localhost:8000`（硬编码在 `RAG.py`）。
3. **SSE 有两套协议**：legal 侧用 `event:` 命名事件；finance 侧用裸 `data:`。改动两端要同步。
4. **Chroma 起不来则 RAG 静默不可用**：lifespan 里 `RAG.init()` 失败只 `pass`。
   排查 RAG 问题先确认 Chroma:8000 与 `models/bge-large-zh-v1.5` 是否就位。
5. **限流偏紧**：全局 200/60s、每用户 20/60s。前端一轮法律对话会并发触发
   askAgent(长流) + sessions + sessions/history，正常使用下容易撞 429。要调先改
   `api/utils/rateLimit.py:28-30`。
6. **CORS 全开**：`api/server.py` 是 `allow_origins=["*"]`（`allow_credentials=False`），
   `my-app/next.config.ts` 给所有路径回 `Access-Control-Allow-Origin: *`。生产前需收紧。
7. **`next.config.ts` 的两条 rewrite 基本失效**：`/api/finance/:path*` 被同名 Route Handler 抢占
   （Next 的 afterFiles rewrite 在文件系统路由之后）；`/api/agent/:path*` 对应的后端
   `api/agent/router.py` 已删除。别指望这两条生效。
8. **`src/lib/utils.ts` 与 `src/lib/utils/` 目录同名共存**（`@/lib/utils` 有解析歧义）。
9. **会话历史读写在两侧**：写在 `agents/legal/memory.py` 的 `checkin`/`update`，
   读在 `api/utils/sessions.py` + `/api/legal/method/sessions*`。定位 key 必须一致：
   `(userId, agentName="legal_agent", threadId)`。
10. **`agents/legal/tools/` 的 5 个脚本无引用**（见上文），别误改。

## 五、文档漂移 / 待清理（已确认，未改代码）

- `agents-project/README.md` 与实际不符：它说"生产创建 `.env`"、"未指定 APP_ENV 时存在 `.env` 读生产"，
  但 `api/utils/config.py` **只读 `.env.development` / `.env.production`**，从不读 `.env`；
  且 `.env.example` 已删除。README 的接口清单也需要按上一节的路由表重写。
- `agents-project/tools/`、`agents-project/skills/` 是空目录。
- 前端 `readBackendError` / `BACKEND_URL` 在多个 route 里重复定义，宜抽公共模块。
- `agents/legal/__init__.py` 的 `_astream_assistant_response` 与 `agents/multiAgent.py` 的
  `call_model` 尾部流式累加 + tool_calls 合并逻辑几乎逐行重复，宜抽到 `agents/utils/streaming.py`。
- 前端 `services-data.ts` 与 `/api/func` 的服务卡片列表重复维护。

## 六、现状与 TODO

- `multiAgent` 里的 `use_finance_agent` 仍是占位（"暂未开通"）；独立 finance agent 只有单股行情工具。
- AI 图片/视频、数据分析、代码助手等前端为 disabled/comingSoon 占位。
- 法务长期记忆已从 InMemoryStore 迁到 Postgres（`agent_store` 表），多实例可用；
  multiAgent / finance 仍用进程内 `BoundedMemorySaver`（重启即失）。
- 用户上传切片 3 天 TTL、`BoundedMemorySaver(max_threads=10)`、legal 快照上限 5 —— 都是刻意的防 OOM 策略，改动需谨慎。
- `SILICONFLOW_API_KEY` 若失效，会连带影响 MainModel/IntentModel/CompressModel/RerankModel 全线。
