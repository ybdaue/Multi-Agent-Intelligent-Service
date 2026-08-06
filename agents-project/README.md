# 智能体项目

AI 智能体框架，支持 FastAPI 接口调用。

## 环境要求

- Python >= 3.10

## 快速启动

```bash
# 1. 进入项目目录
cd agents-project

# 2. 创建虚拟环境（如已存在可跳过）
python -m venv .venv

# 3. 激活虚拟环境
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 4. 安装依赖
pip install -r requirements.txt

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入对应的 API Key（ANTHROPIC_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY）

# 6. 启动 API 服务
uvicorn api.server:app --reload --host 0.0.0.0 --port 8000
```

启动后访问 http://localhost:8000 即可查看 API 文档（Swagger UI）。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/agents` | 列出所有可用智能体 |
| POST | `/agents/{name}/run` | 运行指定智能体（请求体: `{"query": "..."}`） |
| POST | `/api/finance/agent/query` | 金融智能体对话接口 |
| GET | `/api/finance/method/latest` | 获取 A 股实时行情（分页） |
| GET | `/api/finance/method/query` | 按代码查询个股行情 |
