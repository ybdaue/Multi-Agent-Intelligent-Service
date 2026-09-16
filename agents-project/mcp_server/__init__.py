"""MCP Server 包入口。

导入顺序即注册顺序：先建 server，再 import 各工具模块触发 `@mcp.tool` 注册。
"""

from mcp_server.server import mcp
from mcp_server import chroma_tools, postgres_tools  # noqa: F401  (注册副作用)

__all__ = ["mcp"]
