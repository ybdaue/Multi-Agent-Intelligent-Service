from agents.finance.agent import FinanceAgent
from .multiAgent import multiAgent

__all__ = ["FinanceAgent", "multiAgent"]


# 统一出口：名称 → 智能体（类 或 已编译的图实例）
_AGENTS = {
    "finance": FinanceAgent,
    "multiAgent": multiAgent,
}

_instances: dict[str, object] = {}


def get_agent(name: str):
    provider = _AGENTS.get(name)
    if provider is None:
        raise KeyError(f"智能体 '{name}' 不存在")
    if name not in _instances:
        _instances[name] = provider() if isinstance(provider, type) else provider
    return _instances[name]


def list_agents() -> list[str]:
    return list(_AGENTS.keys())
