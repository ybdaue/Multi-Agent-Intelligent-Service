"""通用 MCP Client：把**外部** MCP Server 的工具接进本项目 agent。

与 `mcp_server/`（本项目对外提供的 MCP）方向相反，这里是**消费方**。
外部工具会被转成 LangChain tool，所以 agent 侧 `bind_tools` 的用法完全不变 ——
对 agent 来说，"别人的工具"和本地 `@tool` 没有区别。

用法（应用启动预取一次，之后同步取用）：

    # api/server.py 的 lifespan
    from agents.utils.mcp_client import refresh_mcp_tools, close_mcp
    await refresh_mcp_tools()   # 启动：连接 + 拉取 + 缓存
    ...
    await close_mcp()           # 关闭：断开所有连接

    # tool_registry.get_tools(category) 会自动并入，见 tool_registry/__init__.py

配置：环境变量 `MCP_SERVERS`（JSON）。不设置则一个都不接，功能不受影响。

    {
      "gis": {
        "category": "geo",
        "command": "python", "args": ["gis_server.py"],
        "env": {"GIS_TOKEN": "xxx"}, "cwd": "/opt/gis", "timeout": 30
      },
      "weather": {
        "category": "geo",
        "url": "https://example.com/mcp",
        "headers": {"Authorization": "Bearer xxx"}
      }
    }

规则：
- 有 `command` → stdio（拉起子进程）；有 `url` → streamable-http；都有则 command 优先。
- `category` 决定并入哪个 `get_tools(category)`，默认 `"mcp"`。
- 工具名统一加 `服务名__` 前缀，避免跨 server 重名（LangChain 不允许同名工具）。
- **失败隔离**：单个 server 连不上只跳过它，不影响其它 server 与本地工具。

⚠️ 信任边界：外部工具返回值是**不可信内容**，会被拼进模型上下文，
存在提示注入风险。只接可信来源，不要把外部工具结果当成指令执行。
"""

from contextlib import AsyncExitStack
import json
import os

from langchain_core.tools import StructuredTool


DEFAULT_CATEGORY = "mcp"
DEFAULT_TIMEOUT = 30.0

# 连接与工具缓存：由 refresh_mcp_tools 填充，get_mcp_tools 同步读取
_exit_stack: AsyncExitStack | None = None
_tools_by_category: dict[str, list] = {}
# 自定义 header 时我们自建的 http 客户端；SDK 不管它的生命周期，得自己关
_owned_http_clients: list = []


def _load_server_configs() -> dict:
    """从环境变量 MCP_SERVERS 读外部 server 配置。缺失/非法一律当作"不接"。"""
    raw = os.getenv("MCP_SERVERS")
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[mcp_client] MCP_SERVERS 不是合法 JSON，已忽略：{e}")
        return {}
    if not isinstance(data, dict):
        print("[mcp_client] MCP_SERVERS 顶层必须是对象（服务名 → 配置），已忽略")
        return {}
    return data


def _build_client(spec: dict):
    """按配置造一个高层 mcp Client（尚未连接，交给 AsyncExitStack 进入）。"""
    from mcp.client import Client

    timeout = spec.get("timeout") or DEFAULT_TIMEOUT

    command = spec.get("command")
    if command:
        from mcp.client.stdio import StdioServerParameters

        params = {"command": command, "args": spec.get("args") or []}
        # env 传了就**替换**子进程环境（SDK 语义），不传则继承父进程
        if spec.get("env"):
            params["env"] = spec["env"]
        if spec.get("cwd"):
            params["cwd"] = spec["cwd"]
        return Client(StdioServerParameters(**params), read_timeout_seconds=timeout)

    url = spec.get("url")
    if url:
        headers = spec.get("headers")
        if not headers:
            return Client(url, read_timeout_seconds=timeout)
        # 自定义 header 要自己造 http 客户端再包成 transport
        import httpx2
        from mcp.client.streamable_http import streamable_http_client

        http_client = httpx2.AsyncClient(headers=headers, timeout=timeout)
        _owned_http_clients.append(http_client)
        return Client(
            streamable_http_client(url, http_client=http_client),
            read_timeout_seconds=timeout,
        )

    raise ValueError("MCP server 配置缺少 command 或 url")


def _render_result(result) -> str:
    """把 MCP CallToolResult 拍平成一段文本，给模型吃。"""
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        else:
            dump = getattr(block, "model_dump_json", None)
            parts.append(dump() if callable(dump) else str(block))

    if not parts and getattr(result, "structured_content", None) is not None:
        parts.append(json.dumps(result.structured_content, ensure_ascii=False))

    text = "\n".join(parts) if parts else "（工具无返回值）"
    if getattr(result, "is_error", False):
        return f"外部工具执行失败：{text}"
    return text


def _make_tool(client, server_name: str, tool) -> StructuredTool:
    """把一个 MCP 工具包成 LangChain tool。"""
    mcp_tool_name = tool.name

    async def _call(**kwargs) -> str:
        result = await client.call_tool(mcp_tool_name, kwargs or None)
        return _render_result(result)

    return StructuredTool.from_function(
        coroutine=_call,
        name=f"{server_name}__{mcp_tool_name}",
        description=(
            tool.description
            or f"外部 MCP 工具 {mcp_tool_name}（来自 {server_name}）"
        ),
        # MCP 的 inputSchema 本身就是 JSON Schema，LangChain 的 args_schema 直接收 dict
        args_schema=tool.input_schema or {"type": "object", "properties": {}},
    )


async def refresh_mcp_tools(configs: dict | None = None) -> int:
    """连接所有配置的外部 MCP Server，拉取工具并缓存。返回接入的工具总数。

    configs 为 None 时读环境变量 MCP_SERVERS。重复调用会先断开旧的再重连。
    """
    global _exit_stack, _tools_by_category

    await close_mcp()

    servers = configs if configs is not None else _load_server_configs()
    if not servers:
        _tools_by_category = {}
        return 0

    stack = AsyncExitStack()
    by_category: dict[str, list] = {}
    total = 0

    for name, spec in servers.items():
        if not isinstance(spec, dict):
            print(f"[mcp_client] server「{name}」配置不是对象，已跳过")
            continue
        category = spec.get("category") or DEFAULT_CATEGORY
        try:
            client = _build_client(spec)
            client = await stack.enter_async_context(client)
            listing = await client.list_tools()
        except Exception as e:
            # 失败隔离：一个 server 挂了不能拖垮其它 server 和本地工具
            print(f"[mcp_client] 连接 MCP server「{name}」失败，已跳过：{e}")
            continue

        for t in listing.tools:
            by_category.setdefault(category, []).append(_make_tool(client, name, t))
            total += 1
        print(
            f"[mcp_client] 已接入 MCP server「{name}」："
            f"{len(listing.tools)} 个工具 → 类目 {category}"
        )

    _exit_stack = stack
    _tools_by_category = by_category
    return total


def get_mcp_tools(category: str | None = None) -> list:
    """同步取已缓存的外部工具。category 为 None 时返回全部。

    未调用过 refresh_mcp_tools（或未配置）时返回空列表，调用方无需特判。
    """
    if category is None:
        return [t for tools in _tools_by_category.values() for t in tools]
    return list(_tools_by_category.get(category, []))


async def close_mcp() -> None:
    """断开所有外部 MCP 连接、关闭自建 http 客户端并清空缓存。"""
    global _exit_stack, _tools_by_category

    stack, _exit_stack = _exit_stack, None
    _tools_by_category = {}
    if stack is not None:
        try:
            await stack.aclose()
        except Exception as e:
            print(f"[mcp_client] 关闭 MCP 连接失败（已忽略）：{e}")

    # 顺序要紧：先关 transport（要发终止会话请求），再关它用的 http 客户端
    clients, _owned_http_clients[:] = list(_owned_http_clients), []
    for c in clients:
        try:
            await c.aclose()
        except Exception:
            pass
