"""PostgreSQL 工具：给 agent 提供只读查询能力。

只开放只读 SELECT，用两层保证不误改数据：
1. 语句层：必须是单条 SELECT / WITH ... SELECT；
2. 连接层：`read_only=True`，即便模型绕过语句检查（如数据修改型 CTE），
   数据库也会直接拒绝写入。

`run_readonly_query` / `list_tables` 是纯实现，供 LangChain `@tool` 包装与
MCP Server 复用。
"""

import json
import os

from langchain_core.tools import tool


_MAX_ROWS = 200
_MAX_CHARS = 4000


def _conninfo() -> str:
    conninfo = os.getenv("postgreSQL_URL")
    if not conninfo:
        raise RuntimeError("缺少 postgreSQL_URL，无法连接数据库")
    return conninfo


def _is_readonly_select(sql: str) -> bool:
    s = sql.strip().rstrip(";").strip()
    if not s or ";" in s:  # 空语句或包含多语句
        return False
    return s.split(None, 1)[0].lower() in ("select", "with")


def _cell(value) -> str:
    # bytea 列（temp_file.data / created_file.data）可能很大，不进上下文
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes>"
    if value is None:
        return "NULL"
    return str(value)


def run_readonly_query(sql: str) -> str:
    """执行单条只读 SELECT，返回 JSON 字符串（最多 200 行 / 4000 字符）。"""
    if not _is_readonly_select(sql):
        return "只允许执行单条只读 SELECT 查询。"

    import psycopg

    try:
        with psycopg.connect(
            _conninfo(), options="-c statement_timeout=10000"
        ) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(sql)
                columns = [d.name for d in (cur.description or [])]
                rows = cur.fetchmany(_MAX_ROWS)
    except Exception as e:
        return f"查询失败：{e}"

    payload = {
        "columns": columns,
        "rows": [[_cell(v) for v in row] for row in rows],
        "row_count": len(rows),
    }
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + "...(已截断)"
    return text


def list_tables() -> str:
    """列出当前库 public schema 下所有表名。"""
    import psycopg

    try:
        with psycopg.connect(_conninfo()) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name"
                )
                names = [r[0] for r in cur.fetchall()]
    except Exception as e:
        return f"查询失败：{e}"

    return "、".join(names) if names else "（无表）"


@tool
def query_postgres(sql: str) -> str:
    """对 PostgreSQL 执行一条只读 SELECT 查询，返回 JSON 结果（最多 200 行）。

    参数 sql：单条 SELECT（可写 WITH ... SELECT）；禁止写操作与多语句。
    可用表：laws / bm25 / temp_file / created_file / user_session /
    user_session_history / agent_store / checkpoint 等。
    """
    return run_readonly_query(sql)


@tool
def list_postgres_tables() -> str:
    """列出 PostgreSQL 当前库 public schema 下的所有表名。

    写查询前可先用它确认表名，再配合 query_postgres 查数据。
    """
    return list_tables()
