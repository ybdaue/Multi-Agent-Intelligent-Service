"""Chroma 向量库工具：给 agent 提供语义检索能力。

复用 agents.utils.RAG 的现成封装（懒导入，避免在此模块拉起重依赖）：
- laws_docs  → 系统法律法规，语义检索
- legal_docs → 用户上传文件切片，按 file_id 读回

`search_law_text` / `read_uploaded_text` 是纯实现，供 LangChain `@tool` 包装与
MCP Server 复用。
"""

from langchain_core.tools import tool


def search_law_text(query: str, top_k: int = 5) -> str:
    """在法律法规库（laws_docs）中按语义检索相关法条。"""
    from agents.utils.RAG import retrieve_text

    hits = retrieve_text(query, top_k=top_k)
    if not hits:
        return "未检索到相关法条（向量库可能未就绪）。"

    parts = []
    for i, h in enumerate(hits, 1):
        heading = (h.get("metadata") or {}).get("heading") or ""
        parts.append(f"{i}. {heading}\n{h.get('content', '')}")
    return "\n\n".join(parts)


def read_uploaded_text(file_id: str, page: int = 1, limit: int = 10) -> str:
    """按 file_id 分页读回用户上传文件的切片内容（legal_docs）。"""
    from agents.utils.RAG import get_chunk, get_chunk_num

    total = get_chunk_num(file_id)
    if total == 0:
        return f"未找到 file_id={file_id} 的切片（可能未上传或已过期）。"

    chunks = get_chunk(file_id, page=page, limit=limit)
    if not chunks:
        return "该页无内容。"

    text = "\n\n".join(c["content"] for c in chunks)
    return f"共 {total} 片，当前返回第 {page} 页（{len(chunks)} 片）：\n{text}"


@tool
def search_laws(query: str, top_k: int = 5) -> str:
    """在法律法规库（laws_docs）中按语义检索相关法条。

    参数 query：检索问题或关键词；top_k：返回条数（默认 5）。
    """
    return search_law_text(query, top_k=top_k)


@tool
def read_uploaded_file(file_id: str, page: int = 1, limit: int = 10) -> str:
    """按 file_id 分页读回用户上传文件的切片内容（legal_docs）。

    参数 file_id：上传文件的 md5 id；page / limit：分页参数。
    """
    return read_uploaded_text(file_id, page=page, limit=limit)
