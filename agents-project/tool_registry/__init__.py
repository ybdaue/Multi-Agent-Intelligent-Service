from tool_registry.ak import get_a_stock_price
from tool_registry.chroma import read_uploaded_file, search_laws
from tool_registry.postgres import list_postgres_tables, query_postgres


_registry: dict[str, list] = {}


def register(category: str, tool) -> None:
    _registry.setdefault(category, []).append(tool)


def get_tools(category: str) -> list:
    """本地注册的工具 + 外部 MCP 工具（启动时已由 refresh_mcp_tools 预取）。

    惰性 import：`agents.utils.mcp_client` 会拉起 agents 包，而 agents 又反向 import
    本模块（finance agent），模块级 import 会造成循环（`python -m mcp_server` 时
    tool_registry 先于 agents 加载，直接 ImportError）。
    """
    from agents.utils.mcp_client import get_mcp_tools

    return list(_registry.get(category, [])) + get_mcp_tools(category)


def list_categories() -> list[str]:
    return list(_registry.keys())


register("finance", get_a_stock_price)

# 数据存储操作：PostgreSQL（只读查询）+ Chroma（语义检索）
register("database", query_postgres)
register("database", list_postgres_tables)
register("database", search_laws)
register("database", read_uploaded_file)
