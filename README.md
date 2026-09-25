# AI 智能平台

AI 驱动的智能服务综合平台，集成法律咨询、股票行情分析、AI 小说创作等能力。

## 技术栈

| 层 | 技术 |
|---|------|
| 前端 | Next.js 16, React 19, TypeScript, Sass, next-themes |
| 后端 Agent | Python 3.12, FastAPI, LangChain, LangGraph |
| 数据库 | PostgreSQL 16 (Prisma ORM) |
| 向量库 | ChromaDB (embedding: bge-large-zh-v1.5) |
| 缓存 | Redis 7 |
| AI | DeepSeek / OpenAI / Anthropic / SiliconFlow |

## 项目结构

```
├── my-app/                    # Next.js 前端
│   ├── src/app/
│   │   ├── home/              # 主页（服务大厅）
│   │   │   ├── legal/         # 法律咨询
│   │   │   ├── finance/       # 股票行情/图表
│   │   │   ├── novel/         # AI 小说创作
│   │   │   └── reports/       # 报表
│   │   ├── login/             # 登录
│   │   └── api/               # BFF 路由（代理后端 + AI SDK 直连）
│   ├── prisma/schema/         # 数据库模型（common, novel, legal, agent, finance）
│   └── Dockerfile.dev
│
├── agents-project/            # Python Agent 后端
│   ├── api/
│   │   └── server.py          # FastAPI 入口 (uvicorn, 端口 8080)
│   ├── agents/
│   │   ├── legal/             # 法律咨询智能体 (LangGraph)
│   │   ├── novel/             # 小说创作智能体 (LangGraph)
│   │   └── finance/           # 金融分析智能体
│   └── Dockerfile.dev
│
├── docker-compose.yml         # 本地 Docker 开发编排
└── README.md
```

## 前置条件

| 方式 | 需要安装 |
|------|---------|
| 本地启动 | Node.js 24, Python 3.12, PostgreSQL 16, Redis 7, ChromaDB |
| Docker 启动 | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |

## 快速启动（Docker 方式）

一键启动所有服务，无需本地安装运行环境。

```bash
# 1. 构建镜像
docker compose build

# 2. 启动所有服务
docker compose up

# 3. 浏览器打开
open http://localhost:3000
```

容器清单：

| 服务 | 端口 | 说明 |
|------|------|------|
| nextjs | 3000 | Next.js 开发服务器 (HMR 热更新) |
| agents-api | 8080 | FastAPI Agent 后端 (--reload 自动重启) |
| postgres | 5432 | PostgreSQL 16 |
| redis | 6379 | Redis 7 |
| chroma | 8000 | ChromaDB 向量库 |

文件修改会自动热更新。数据库持久化在 Docker volumes 中，重启不丢失。

### 常用 Docker 命令

```bash
docker compose up -d           # 后台启动
docker compose down            # 停止服务
docker compose down -v         # 停止并删除数据卷（重置数据库）
docker compose logs -f         # 查看日志
docker compose build           # 重新构建镜像
docker compose exec nextjs sh  # 进入容器终端

# 手动执行 Prisma 迁移
docker compose exec nextjs npx prisma migrate deploy
```

## 本地启动（无 Docker）

如果需要单独调试前端或后端，也可以直接在本地启动。

### 环境变量

项目使用 `.env.development`（开发）和 `.env.production`（生产）管理配置，**均已 gitignore**，需要自行创建。

- `my-app/.env.development` — 前端环境变量（API 地址、Auth URL、API Key 等）
- `agents-project/.env.development` — 后端环境变量（AI 模型 API Key、数据库连接串等）

### 启动 PostgreSQL / Redis / Chroma

```bash
# PostgreSQL 16
docker run -d --name pg \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=123456 \
  -e POSTGRES_DB=demo \
  -p 5432:5432 \
  postgres:16

# Redis 7
docker run -d --name redis -p 6379:6379 redis:7

# ChromaDB
docker run -d --name chroma -p 8000:8000 chromadb/chroma
```

### 启动后端

```bash
cd agents-project

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate       # Linux/Mac
# .venv\Scripts\activate        # Windows

# 安装依赖
pip install -r requirements.txt

# 启动 FastAPI
uvicorn api.server:app --host 0.0.0.0 --port 8080 --reload
```

> 注意：约 2GB 的 [bge-large-zh-v1.5](https://huggingface.co/BAAI/bge-large-zh-v1.5) 中文 Embedding 模型需预先下载到 `agents-project/models/` 目录（已 gitignore）。也可让程序首次运行时报错后自动下载。

### 启动前端

```bash
cd my-app

npm install

# 生成 Prisma Client + 启动开发服务器
npm run dev

# 或分步执行：
npx prisma generate
npx next dev -p 3000
```

首次部署需初始化数据库表结构：

```bash
npx prisma migrate deploy
```

浏览器打开 `http://localhost:3000`。

## 功能模块

- **法律咨询** — AI 律师智能体，支持法律法规检索、案情分析、文书起草
- **股票行情** — A 股实时行情、K 线图、技术指标（数据源：akshare）
- **AI 小说** — 多轮对话式小说创作，含情节规划、章节生成、编辑修改
- **服务大厅** — 统一入口，卡片式展示所有可用服务
- **用户系统** — 邮箱/密码登录（better-auth），会话管理

## 环境变量参考

### my-app

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 |
| `NEXT_PUBLIC_API_URL` | Agent 后端地址 |
| `NEXT_PUBLIC_BETTER_AUTH_URL` | 认证服务地址 |
| `APIKEY` | AI SDK API Key |

### agents-project

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `ANTHROPIC_API_KEY` | Anthropic API Key |
| `OPENAI_API_KEY` | OpenAI API Key |
| `SILICONFLOW_API_KEY` | SiliconFlow API Key |
| `TICKFLOW_KEY` | Tickflow Key |
| `postgreSQL_URL` | PostgreSQL 连接串 |
| `redis_URL` | Redis 连接串 |
| `CHROMA_SERVER_HOST` | ChromaDB 主机地址（默认 localhost） |
| `APP_ENV` | 运行环境（development / production） |