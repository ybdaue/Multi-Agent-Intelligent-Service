"""有界专用线程池：把重同步活（解析/embedding/Chroma/PG/docx）从事件循环和
LangGraph 共享的默认池里隔离出来，避免拖垮并发请求。
"""

import asyncio
import contextvars
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Callable, TypeVar

# 预处理：文件解析 + SentenceTransformer 编码 + Chroma 写入，单请求很重、内存占用高
PREPROCESS_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="preproc")
# RAG/DB 读写：Chroma 分页取切片、法条检索、PG 文件字节读写、docx 生成
RAG_IO_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rag-io")

_T = TypeVar("_T")


async def run_in_pool(executor: Executor, func: Callable[..., _T], *args) -> _T:
    """在专用线程池里跑同步函数，并复制当前 context。

    loop.run_in_executor(custom_executor, fn) 不会复制 contextvars，会让 fn 里的
    get_config() 拿到空配置；这里手动 copy_context 对齐 langchain 默认池的行为。
    """
    ctx = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(executor, ctx.run, func, *args)
