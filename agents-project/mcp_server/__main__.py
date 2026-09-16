"""协议入口：`python -m mcp_server` 启动 MCP Server。

传输方式暂用 SDK 默认（stdio），后续需要 HTTP 时改为
`mcp.run(transport="streamable-http")` 即可，不用动工具定义。
"""

from mcp_server import mcp


if __name__ == "__main__":
    mcp.run()
