import os
from typing import Any, Optional

from langchain_openai import ChatOpenAI

# 各厂商 OpenAI 兼容端点；None 表示用 ChatOpenAI 默认
BASE_URLS: dict[str, Optional[str]] = {
    "openai": None,
    "deepseek": "https://api.deepseek.com",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/",  # GLM
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "guiji":"https://api.siliconflow.cn/v1"
}

# 各厂商 api_key 对应的环境变量名
API_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "guiji":"SILICONFLOW_API_KEY"
}

# 兼容叫法：create_chat_model("glm", ...) -> zhipu
PROVIDER_ALIASES: dict[str, str] = {"glm": "zhipu"}


def _normalize_provider(provider: str) -> str:
    provider = PROVIDER_ALIASES.get(provider, provider)
    if provider not in BASE_URLS:
        raise ValueError(
            f"未知厂商 {provider!r}，可选：{sorted(BASE_URLS)}"
        )
    return provider


def create_chat_model(
    provider: str,
    model: str,
    temperature: float = 0.3,
    **kwargs: Any,
) -> ChatOpenAI:
    """创建指定厂商的模型，按厂商自动取 base_url（BASE_URLS）与 api_key（环境变量）。

    provider: openai / deepseek / zhipu(或 glm) / qwen
    model:    具体模型名，如 "deepseek-reasoner"、"qwen-plus"
    其余参数（temperature 等）透传给 ChatOpenAI。
    """
    provider = _normalize_provider(provider)

    key = os.getenv(API_KEY_ENV[provider])
    if not key:
        raise ValueError(
            f"缺少 {provider} 的 API key：请在当前 env 文件里配置环境变量 "
            f"{API_KEY_ENV[provider]}。"
        )

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=key,
        base_url=BASE_URLS[provider],
        **kwargs,
    )


# 模型工厂
def MainModel(temperature: float = 0.3,**kwargs: Any):
    # return create_chat_model("qwen", "qwen3.8-flash", temperature=temperature, **kwargs)
    return create_chat_model("guiji", "deepseek-ai/DeepSeek-V4-Flash", temperature=temperature, **kwargs)
    # return create_chat_model("deepseek", "deepseek-v4-flash", temperature=temperature, **kwargs)

def IntentModel(temperature: float = 0.3,**kwargs: Any):
    return create_chat_model("guiji", "Qwen/Qwen3-8B", temperature=temperature, **kwargs)

def CompressModel(temperature: float = 0.3,**kwargs: Any):
    return create_chat_model("guiji", "Qwen/Qwen3-8B", temperature=temperature, **kwargs)

def RerankModel(
    query: str,
    documents: list[str],
    top_n: int = 5,
    timeout: int = 30,
) -> list[tuple[int, float]]:
    """交叉编码器重排：对候选文档按与 query 的相关性打分。

    直连 SiliconFlow /v1/rerank（BAAI/bge-reranker-v2-m3），返回已按
    relevance_score 降序的 [(index, relevance_score), ...]；失败抛异常由调用方降级。

    Args:
        query:    检索问题/关键词
        documents: 候选文档原文列表（顺序即索引参照）
        top_n:    返回前 n 个最相关结果
        timeout:  请求超时（秒）
    """
    import os

    import requests

    key = os.getenv("SILICONFLOW_API_KEY")
    if not key:
        raise ValueError("缺少 SILICONFLOW_API_KEY")

    resp = requests.post(
        "https://api.siliconflow.cn/v1/rerank",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "BAAI/bge-reranker-v2-m3",
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": False,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return [
        (r["index"], r["relevance_score"])
        for r in resp.json()["results"]
    ]