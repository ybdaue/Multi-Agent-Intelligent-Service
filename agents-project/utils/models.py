import os
from dataclasses import dataclass, field
from typing import Any, Optional

from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI


@dataclass
class AgentContext:
    agent_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    tool: str
    success: bool
    data: dict[str, Any]


@dataclass
class AgentResponse:
    agent: str
    results: list[ToolResult]


def create_openai_model(
    model: str = "gpt-4o",
    temperature: float = 0.7,
    **kwargs: Any,
) -> ChatOpenAI:
    return ChatOpenAI(model=model, temperature=temperature, **kwargs)


def create_deepseek_model(
    model: str = "deepseek-chat",
    temperature: float = 0.7,
    api_key: Optional[str] = None,
    **kwargs: Any,
) -> ChatDeepSeek:
    resolved_key = api_key or os.getenv("DEEPSEEK_API_KEY")
    if not resolved_key:
        raise ValueError(
            "DEEPSEEK_API_KEY 未设置。"
            "请通过 api_key 参数传入，或设置 DEEPSEEK_API_KEY 环境变量。"
        )
    return ChatDeepSeek(
        model=model,
        temperature=temperature,
        api_key=resolved_key,
        **kwargs,
    )
