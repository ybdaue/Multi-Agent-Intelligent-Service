import json
import os
import uuid
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


def _has_tool_traffic(messages) -> bool:
    """请求里是否重放了工具循环（含 assistant.tool_calls 或 tool 结果）。

    只看会真的变成出站 tool_calls 的消息：tool_calls / invalid_tool_calls /
    additional_kwargs 里塞的 tool_calls|function_call——后两者不体现在 message.tool_calls 上，
    若只看 tool_calls 会漏判。
    """
    for msg in messages:
        if type(msg).__name__ == "ToolMessage":
            return True
        if type(msg).__name__ != "AIMessage":
            continue
        kwargs = getattr(msg, "additional_kwargs", None) or {}
        if (
            getattr(msg, "tool_calls", None)
            or getattr(msg, "invalid_tool_calls", None)
            or "tool_calls" in kwargs
            or "function_call" in kwargs
        ):
            return True
    return False


def _short_id(value) -> str:
    """取 id 尾部：provider 的 id 形如 call_00_UZCfZl...9865，前缀相同，尾部才有区分度。"""
    return str(value)[-8:]


def _describe_message(msg) -> str:
    """把一条消息压成一行，重点暴露 tool_calls 与 tool_call_id 的配对关系。"""
    kind = type(msg).__name__
    if kind == "ToolMessage":
        return f"tool#{_short_id(getattr(msg, 'tool_call_id', None))}"
    if kind == "AIMessage":
        kwargs = getattr(msg, "additional_kwargs", None) or {}
        parts = []
        calls = getattr(msg, "tool_calls", None) or []
        if calls:
            pairs = ",".join(f"{(c.get('name') or '?')}#{_short_id(c.get('id'))}" for c in calls)
            parts.append(f"calls=[{pairs}]")
        invalid = getattr(msg, "invalid_tool_calls", None) or []
        if invalid:
            pairs = ",".join(f"{(c.get('name') or '?')}#{_short_id(c.get('id'))}" for c in invalid)
            parts.append(f"INVALID=[{pairs}]")
        if "tool_calls" in kwargs:
            parts.append(f"kwargs.tool_calls={len(kwargs['tool_calls'])}")
        if "function_call" in kwargs:
            parts.append("kwargs.function_call")
        return "ai(" + (" ".join(parts) if parts else "no-tools") + ")"
    return {"SystemMessage": "sys", "HumanMessage": "human"}.get(kind, kind.lower())


def _format_request(messages) -> str:
    return " ".join(_describe_message(m) for m in messages)


class _ChatOpenAI(ChatOpenAI):
    """兼容端点（DeepSeek 等）对消息序列要求严格，在响应入口做两处清洗：

    1. 丢弃 args 解析失败的 tool_call（invalid_tool_calls）。langchain-openai 会把它们
       当成 tool_calls 原样发回模型，但 create_agent 只为 tool_calls 执行/生成 ToolMessage，
       于是下一轮请求里 tool_calls 无人应答，DeepSeek 直接 400：
       "insufficient tool messages following tool_calls message"。
    2. 补齐缺失的 tool_call id：id 为空时 ToolMessage 无法与之配对，同样是 400。
    """

    @property
    def _label(self) -> str:
        # 日志绝不能再抛异常：出错分支里一旦抛，会顶掉 provider 的原始报错
        return getattr(self, "model_name", None) or getattr(self, "model", "?")

    def _log_request(self, messages) -> None:
        """打印重放工具循环的出站序列（这是唯一能触发序列类 400 的请求形态）。"""
        try:
            if _has_tool_traffic(messages):
                print(f"[llm] 出站序列 model={self._label}: {_format_request(messages)}")
        except Exception:
            pass

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._log_request(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self._log_request(messages)
        try:
            return await super()._agenerate(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )
        except Exception:
            # 出错时把出站序列再打一遍，便于对照 provider 的报错定位是哪条 tool_call 没被应答
            print(f"[llm] 请求失败 model={self._label}: {_format_request(messages)}")
            raise

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        for generation in result.generations:
            message = generation.message
            if getattr(message, "invalid_tool_calls", None):
                # 先留证据再清洗：finish_reason=length 说明是撞输出上限被截断，
                # =stop 而 args 仍是残的，则多半是模型自己写坏了 JSON（引号未转义等）。
                finish_reason = (generation.generation_info or {}).get("finish_reason")
                print(
                    f"[llm] invalid_tool_calls={len(message.invalid_tool_calls)} "
                    f"finish_reason={finish_reason!r}"
                )
                for call in message.invalid_tool_calls:
                    print(
                        f"[llm]   tool={call.get('name')!r} id={call.get('id')!r}\n"
                        f"[llm]   raw_args={call.get('args')!r}\n"
                        f"[llm]   parse_error={call.get('error')}"
                    )
                message.invalid_tool_calls = []
            for call in getattr(message, "tool_calls", None) or []:
                if not call.get("id"):
                    print(f"[llm] tool_call 缺 id，已补齐：{call.get('name')!r}")
                    call["id"] = uuid.uuid4().hex
        return result


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

    return _ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=key,
        base_url=BASE_URLS[provider],
        **kwargs,
    )


def parse_json_value(text: Any) -> Any:
    """从模型文本里取出第一个完整的 JSON 值（对象或数组），容忍 ```json 围栏与前后解释文字。

    用 raw_decode 逐个候选起点试解，只认第一个能完整解析的值，因此对象/数组之后
    跟的任何多余内容（另一个对象、解释文字）都会被忽略——早先"首 { 到末 }"的截取
    在模型输出裸数组 [ {...}, {...} ] 时会切出 "{...},{...}" 并抛 Extra data。

    DeepSeek V4 默认开启 thinking，thinking 模式下服务端直接拒绝 tool_choice 与
    response_format(json_schema)，provider 原生结构化输出和 ToolStrategy 都会 400。
    因此结构化输出只能靠提示词约束 + 自行解析，这里做容错提取。
    解析失败抛 ValueError，由调用方决定回退。
    """
    if not isinstance(text, str):
        text = str(text)
    s = text.strip()
    if s.startswith("```"):
        # 去掉 ``` 或 ```json 围栏，再剥掉结尾的 ```
        s = s.split("\n", 1)[-1] if "\n" in s else s
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(s):
        if ch not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(s, idx)
        except json.JSONDecodeError:
            continue
        return value
    raise ValueError(f"未在模型输出中找到 JSON：{text[:200]!r}")


def parse_json_object(text: Any) -> dict:
    """从模型文本里取出 JSON 对象（见 parse_json_value）。取到的不是对象则抛异常。"""
    value = parse_json_value(text)
    if not isinstance(value, dict):
        raise ValueError(f"模型输出不是 JSON 对象：{text[:200]!r}")
    return value


# 模型工厂
def MainModel(temperature: float = 0.3,**kwargs: Any):
    # return create_chat_model("qwen", "qwen3.8-flash", temperature=temperature, **kwargs)
    # return create_chat_model("guiji", "deepseek-ai/DeepSeek-V4-Flash", temperature=temperature, **kwargs)
    return create_chat_model("deepseek", "deepseek-flash", temperature=temperature, **kwargs)

def IntentModel(temperature: float = 0.3,**kwargs: Any):
    return create_chat_model("deepseek", "deepseek-flash", temperature=temperature, **kwargs)
    # return create_chat_model("guiji", "Qwen/Qwen3-8B", temperature=temperature, **kwargs)

def CompressModel(temperature: float = 0.3,**kwargs: Any):
    return create_chat_model("deepseek", "deepseek-flash", temperature=temperature, **kwargs)
    # return create_chat_model("guiji", "Qwen/Qwen3-8B", temperature=temperature, **kwargs)

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