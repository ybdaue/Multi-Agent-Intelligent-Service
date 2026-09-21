import time
from typing import Union

from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.types import Command

from ...utils.executor import PREPROCESS_EXECUTOR, run_in_pool
from ...utils.parse import parse_and_chunk
from ...utils.RAG import FILE_TTL_SECONDS, delete_expired_chunks, get_chunk_num, upsert_chunks
from ..state import State


def _preprocessing_sync(state: State) -> Union[dict, Command]:
    file_source = state.get("file_source")
    if not file_source:
        # 兜底：图路由已保证无文件轮次不进本节点，这里再挡一层
        return {"doc_ids": []}

    print("正在预处理文件")
    # 惰性 TTL 清扫：上传前先清掉过期切片，控制向量库总量
    try:
        delete_expired_chunks(time.time() - FILE_TTL_SECONDS)
    except Exception:
        pass

    # 内容哈希查重：TTL 清扫后仍能查到该 file_id 的切片，说明是同一文件且切片未过期，直接复用
    if get_chunk_num(file_source["file_id"]) > 0:
        return {"doc_ids": [file_source["file_id"]], "error": None}

    try:
        chunks = parse_and_chunk(file_source)
    except Exception as e:
        return Command(
            update={
                "error": f"文件解析异常: {e}",
                "messages": [
                    AIMessage(content=f"抱歉，文件解析失败：{e}")
                ],
                "doc_ids": [],
            },
            goto=END,
        )

    if not chunks:
        return Command(
            update={
                "error": "文件解析失败，可能是扫描版 PDF",
                "messages": [
                    AIMessage(content="抱歉，文件解析失败，上传文件格式有误。")
                ],
                "doc_ids": [],
                "chunk_count": 0,
            },
            goto=END
        )

    success = upsert_chunks(chunks)
    if not success:
        return Command(
            update={
                "error": "向量数据库写入失败",
                "messages": [
                    AIMessage(content="抱歉，向量数据库写入失败，请联系管理员。")
                ],
                "doc_ids": [],
                "chunk_count": 0,
            },
            goto=END
        )

    return {
        "doc_ids": [chunks[0]["metadata"]["file_id"]],
        "error": None,
    }


async def preprocessing(state: State) -> dict:
    """解析/切片/embedding/Chroma 写入都是重同步活，放专用池，避免占满共享线程池。"""
    return await run_in_pool(PREPROCESS_EXECUTOR, _preprocessing_sync, state)
