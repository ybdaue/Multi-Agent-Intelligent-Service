import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from contextlib import asynccontextmanager

# 把项目根目录加入 sys.path，确保各子包可以正常导入
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# 加载 .env 文件，不存在则回退到 .env.example
env_path = project_root / ".env"
if not env_path.exists():
    env_path = project_root / ".env.example"
load_dotenv(env_path)

from fastapi import FastAPI, HTTPException,Form,UploadFile,File
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from agents import get_agent, list_agents
from agents import RAG
from api.agent.router import router as finance_agent_router
from api.finance.method_router import router as finance_method_router
from agents import get_agent
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
import io
import os
import tempfile


OUTPUT_DIR = project_root / "agent_workspace" / "output"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：尝试初始化 RAG，失败不阻塞
    RAG.init()
    yield
    # 关闭时：无需额外清理（Chroma 客户端自动断开）


app = FastAPI(title="智能体 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://26.41.157.27:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(finance_agent_router)
app.include_router(finance_method_router)


class RunQuery(BaseModel):
    query: str


class RunResponse(BaseModel):
    agent: str
    result: str


@app.get("/health")
def health():
    return {"status": "ok", "rag": {"ready": RAG.is_ready()}}

@app.get("/agents")
def agents():
    return {"agents": list_agents()}


@app.post("/agents/{name}/run", response_model=RunResponse)
def run_agent(name: str, body: RunQuery):
    try:
        agent = get_agent(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"智能体 '{name}' 不存在")
    result = agent.run(body.query)
    return RunResponse(agent=name, result=result)

@app.post("/multiAgent")
async def call_agent(
    userId: int,
    threadId: str = Form(...),
    text: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    if not text.strip():
        raise HTTPException(status_code=400, detail="至少上传一段文本")

    config = {"configurable": {"thread_id": threadId, "userId": userId}}
    input_state = {
        "messages": [HumanMessage(text)],
        "userId": userId,
        "user_message": text,
    }

    tmp_path_to_clean: Optional[str] = None

    if file is not None:
        content = await file.read()
        file_size = len(content)
        # 用内容哈希作为 file_id：同一文件重复上传得到相同 id，Chroma upsert 原地覆盖，不产生重复切片
        file_id = hashlib.md5(content).hexdigest()
        suffix = os.path.splitext(file.filename or "")[1]

        if file_size <= 5 * 1024 * 1024:
            input_state["file_source"] = {
                "type": "bytes",
                "suffix": suffix,
                "content": content,
                "file_id": file_id,
            }
        else:
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix, prefix=f"{file_id}_upload_"
            )
            tmp.write(content)
            tmp.close()
            tmp_path_to_clean = tmp.name
            input_state["file_source"] = {
                "type": "path",
                "suffix": suffix,
                "content": tmp_path_to_clean,
                "file_id": file_id,
            }
    else:
        input_state["file_source"] = None

    async def event_stream():
        nonlocal tmp_path_to_clean
        has_file = False
        streamed_any_token = False
        try:
            async for event in get_agent("multiAgent").astream(
                input_state, config, stream_mode=["messages", "values"]
            ):
                if not isinstance(event, tuple) or len(event) != 2:
                    continue

                mode, data = event

                if mode == "messages":
                    msg, metadata = data
                    if not isinstance(msg, AIMessageChunk):
                        continue
                    content = msg.content
                    if isinstance(content, str) and content:
                        streamed_any_token = True
                        yield (
                            f"event: token\n"
                            f"data: {json.dumps({'text': content}, ensure_ascii=False)}\n\n"
                        )
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text" and c["text"]:
                                streamed_any_token = True
                                yield (
                                    f"event: token\n"
                                    f"data: {json.dumps({'text': c['text']}, ensure_ascii=False)}\n\n"
                                )

                elif mode == "values":
                    state = data
                    output_file = state.get("output_file")
                    if output_file and not has_file:
                        has_file = True
                        path_str = output_file.get("content", "")
                        filename = (
                            os.path.basename(path_str)
                            if isinstance(path_str, str) else ""
                        )
                        if filename:
                            yield (
                                f"event: file_generated\n"
                                f"data: {json.dumps({'userId': userId, 'filename': filename})}\n\n"
                            )

            if streamed_any_token or has_file:
                yield f"event: done\ndata: {json.dumps({'message': 'ok'})}\n\n"
            else:
                yield (
                    f"event: error\n"
                    f"data: {json.dumps({'message': '后端未返回流式内容，流式传输失败'})}\n\n"
                )

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

        finally:
            if tmp_path_to_clean and os.path.exists(tmp_path_to_clean):
                try:
                    os.remove(tmp_path_to_clean)
                except OSError:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@app.get("/download/{userId}/{filename:path}")
async def download_file(userId: int, filename: str):
    """下载 agent 生成的文书文件（.docx）。

    文件按 userId 隔离存放于 agent_workspace/output/{userId}/{filename}。
    """
    # 按 userId 定位目录，防止跨用户访问
    user_output_dir = (OUTPUT_DIR / str(userId)).resolve()
    if not str(user_output_dir).startswith(str(OUTPUT_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法用户 ID")

    safe_path = (user_output_dir / filename).resolve()
    if not str(safe_path).startswith(str(user_output_dir)):
        raise HTTPException(status_code=400, detail="非法文件名")

    if not safe_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    return FileResponse(
        safe_path,
        filename=safe_path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )