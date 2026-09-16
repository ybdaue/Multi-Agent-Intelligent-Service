"""MCP 工具：Chroma 语义检索。

实现复用 `tool_registry.chroma` 的纯函数，这里只做 MCP 注册 + 注解声明。
"""

from mcp.types import ToolAnnotations

from mcp_server.server import mcp
from tool_registry.chroma import read_uploaded_text, search_law_text


_READONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


@mcp.tool(
    name="search_laws",
    description="在法律法规库（laws_docs）中按语义检索相关法条。query：问题或关键词；top_k：返回条数（默认 5）。",
    annotations=_READONLY,
)
def search_laws(query: str, top_k: int = 5) -> str:
    return search_law_text(query, top_k=top_k)


@mcp.tool(
    name="read_uploaded_file",
    description="按 file_id（上传文件 md5）分页读回用户上传文件的切片内容（legal_docs）。",
    annotations=_READONLY,
)
def read_uploaded_file(file_id: str, page: int = 1, limit: int = 10) -> str:
    return read_uploaded_text(file_id, page=page, limit=limit)
