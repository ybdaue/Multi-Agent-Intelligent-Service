import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（agents-project/），确保各子包可直接导入
# 本文件在 api/utils/ 下，向上三级才是 agents-project/
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 按运行环境选择 env 文件（均已 gitignore，不会提交）：
#   APP_ENV=production / prod -> .env.production（生产/真实 Key，仅供生产）
#   其它（含未设置）           -> .env.development（本地开发 Key）
# 必须在 import agents（其模块级会读 DEEPSEEK_API_KEY 等）之前完成。
mode = os.getenv("APP_ENV", "").strip().lower()
if mode in ("production", "prod"):
    candidates = [".env.production", ".env.development"]
else:
    candidates = [".env.development"]

env_path = next((project_root / c for c in candidates if (project_root / c).exists()), None)
if env_path is not None:
    load_dotenv(env_path)

# agent 生成文书输出根目录，下载接口按 userId 分子目录隔离
OUTPUT_DIR = project_root / "agent_workspace" / "output"
