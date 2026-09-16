"""MCP 工具：PostgreSQL 只读查询。

实现复用 `tool_registry.postgres` 的纯函数，这里只做 MCP 注册 + 注解声明。
"""

from mcp.types import ToolAnnotations

from mcp_server.server import mcp
from tool_registry.postgres import list_tables, run_readonly_query


_READONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


@mcp.tool(
    name="query_postgres",
    description=(
        "对 PostgreSQL 执行一条只读 SELECT 查询，返回 JSON（最多 200 行）。"
        "参数 sql：单条 SELECT（可含 WITH ... SELECT），禁止写操作与多语句。"
        "可用表：laws / bm25 / temp_file / created_file / user_session / "
        "user_session_history / agent_store / checkpoint 等。"
    ),
    annotations=_READONLY,
)
def query_postgres(sql: str) -> str:
    return run_readonly_query(sql)


@mcp.tool(
    name="list_postgres_tables",
    description=(
        "列出 PostgreSQL 当前库 public schema 下的所有表名；"
        "写查询前可先用它确认表名，再配合 query_postgres 查数据。"
    ),
    annotations=_READONLY,
)
def list_postgres_tables() -> str:
    return list_tables()
