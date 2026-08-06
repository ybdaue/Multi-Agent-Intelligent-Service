from mcp.ak import get_a_stock_price


_registry: dict[str, list] = {}


def register(category: str, tool) -> None:
    _registry.setdefault(category, []).append(tool)


def get_tools(category: str) -> list:
    return _registry.get(category, [])


def list_categories() -> list[str]:
    return list(_registry.keys())


register("finance", get_a_stock_price)
