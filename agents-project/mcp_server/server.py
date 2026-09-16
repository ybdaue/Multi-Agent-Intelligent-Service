"""真正的 MCP Server 实例与生命周期。

用官方 `mcp` SDK 的 MCPServer（v2 起由 FastMCP 更名而来）：
- 协议入口 / 生命周期 / 能力协商由 SDK 处理；
- 工具在 `postgres_tools` / `chroma_tools` 里通过 `@mcp.tool(...)` 注册，
  并带 ToolAnnotations（只读、幂等、无副作用）。

传输方式（stdio / streamable-http）暂不绑定，由 `__main__` 调用 `mcp.run()`
时再定；当前只保证 server 主体与工具定义正确。
"""

from contextlib import asynccontextmanager
import os

from mcp.server.mcpserver import MCPServer


@asynccontextmanager
async def lifespan(server: MCPServer):
    """Server 启停钩子：启动时校验依赖环境，退出时留出清理位。"""
    if not os.getenv("postgreSQL_URL"):
        # 只告警不拦：finance 工具不依赖 PG，仍可正常启动
        print("[mcp_server] 未设置 postgreSQL_URL，数据库类工具将不可用")
    yield {"datastores": ["postgres", "chroma"]}


mcp = MCPServer("legal-agent-tools", lifespan=lifespan)
