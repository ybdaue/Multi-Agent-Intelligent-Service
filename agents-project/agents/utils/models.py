import json
import os
import uuid
from typing import Any, Optional

from langchain_openai import ChatOpenAI

# ── 供应商配置 ────────────────────────────────────────────────

BASE_URLS: dict[str, Optional[str]] = {
    "openai": None,
    "deepseek": "https://api.deepseek.com",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/",  # GLM
    "qwen": "https://maas.qianwenaiapi.com/compatible-mode/v1",
    "guiji":"https://api.siliconflow.cn/v1"
}

API_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "guiji":"SILICONFLOW_API_KEY"
}

PROVIDER_ALIASES: dict[str, str] = {"glm": "zhipu"}


def _normalize_provider(provider: str) -> str:
    provider = PROVIDER_ALIASES.get(provider, provider)
    if provider not in BASE_URLS:
        raise ValueError(f"未知厂商 {provider!r}，可选：{sorted(BASE_URLS)}")
    return provider


# ── ChatOpenAI 子类（tool_call 清洗 + 用量采集）────────────

def _has_tool_traffic(messages) -> bool:
    """请求里是否包含需出站 tool_call 的消息（tool / assistant.tool_calls）。"""
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
    return str(value)[-8:]


def _describe_message(msg) -> str:
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
    """兼容端点的 ChatOpenAI 子类，在响应入口做两处清洗：

    1. 丢弃 args 解析失败的 tool_call（invalid_tool_calls），否则下一轮请求 DeepSeek 会 400。
    2. 补齐缺失的 tool_call id，使 ToolMessage 能与之配对。
    """

    _provider_name: str = ""

    def __init__(self, *args, _provider_name: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._provider_name = _provider_name

    @property
    def _label(self) -> str:
        return getattr(self, "model_name", None) or getattr(self, "model", "?")

    def _log_request(self, messages) -> None:
        try:
            if _has_tool_traffic(messages):
                print(f"[llm] 出站序列 model={self._label}: {_format_request(messages)}")
        except Exception:
            pass

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._log_request(messages)
        result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        self._collect_usage(result)
        return result

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self._log_request(messages)
        try:
            result = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
            self._collect_usage(result)
            return result
        except Exception:
            print(f"[llm] 请求失败 model={self._label}: {_format_request(messages)}")
            raise

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        """流式底层：逐块 yield 并在流结束后采集 usage_metadata 记录计费。

        ChatOpenAI._astream 仅作路由转发（Chat Completions / Responses API），
        不做计费采集。_agenerate_with_cache 调用此方法（走 _should_stream 分支时），
        若 _collect_usage 未被触发，会漏记 token → 在此补充采集。
        """
        self._log_request(messages)
        final_usage = None
        try:
            async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                # ChatGenerationChunk → AIMessageChunk → usage_metadata
                msg = getattr(chunk, "message", None)
                meta = getattr(msg, "usage_metadata", None) if msg else None
                if meta:
                    final_usage = meta
                yield chunk
        except Exception:
            print(f"[llm] 流式请求失败 model={self._label}: {_format_request(messages)}")
            raise
        if final_usage:
            from .billing import record_llm_call
            record_llm_call(
                provider=self._provider_name, model_name=self._label,
                input_tokens=final_usage.get("input_tokens", 0),
                output_tokens=final_usage.get("output_tokens", 0),
            )

    async def astream(self, input, config=None, *, stop=None, **kwargs):
        """流式调用，在流结束后采集 usage_metadata 记录计费。

        LangChain 在 astream 层（而非 _astream 层）给最后一块 chunk 附加 usage_metadata，
        因此必须在此层采集。
        """
        final_usage = None
        async for chunk in super().astream(input, config=config, stop=stop, **kwargs):
            meta = getattr(chunk, "usage_metadata", None)
            if meta:
                final_usage = meta
            yield chunk

        if final_usage:
            from .billing import record_llm_call
            record_llm_call(
                provider=self._provider_name, model_name=self._label,
                input_tokens=final_usage.get("input_tokens", 0),
                output_tokens=final_usage.get("output_tokens", 0),
            )

    def _collect_usage(self, result):
        from .billing import record_llm_call
        try:
            for generations in getattr(result, "generations", None) or []:
                for generation in generations:
                    msg = getattr(generation, "message", None)
                    if msg is None:
                        continue
                    meta = getattr(msg, "usage_metadata", None)
                    if not meta:
                        continue
                    record_llm_call(
                        provider=self._provider_name, model_name=self._label,
                        input_tokens=meta.get("input_tokens", 0),
                        output_tokens=meta.get("output_tokens", 0),
                    )
        except Exception:
            pass

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        for generation in result.generations:
            message = generation.message
            # 修正 model_provider：ChatOpenAI 对所有兼容 API 都硬编码 "openai"
            resp_meta = getattr(message, "response_metadata", None) or {}
            if self._provider_name and resp_meta.get("model_provider") != self._provider_name:
                resp_meta["model_provider"] = self._provider_name
            if getattr(message, "invalid_tool_calls", None):
                finish_reason = (generation.generation_info or {}).get("finish_reason")
                print(f"[llm] invalid_tool_calls={len(message.invalid_tool_calls)} finish_reason={finish_reason!r}")
                for call in message.invalid_tool_calls:
                    print(f"[llm]   tool={call.get('name')!r} id={call.get('id')!r}\n"
                          f"[llm]   raw_args={call.get('args')!r}\n"
                          f"[llm]   parse_error={call.get('error')}")
                message.invalid_tool_calls = []
            for call in getattr(message, "tool_calls", None) or []:
                if not call.get("id"):
                    print(f"[llm] tool_call 缺 id，已补齐：{call.get('name')!r}")
                    call["id"] = uuid.uuid4().hex
        return result


# ── 模型创建 ──────────────────────────────────────────────────

def create_chat_model(
    provider: str,
    model: str,
    temperature: float = 0.3,
    **kwargs: Any,
) -> ChatOpenAI:
    """创建指定厂商的模型，自动取 base_url 与 api_key。"""
    provider = _normalize_provider(provider)
    key = os.getenv(API_KEY_ENV[provider])
    if not key:
        raise ValueError(f"缺少 {provider} 的 API key：请在 env 中配置 {API_KEY_ENV[provider]}")
    return _ChatOpenAI(
        model=model, temperature=temperature, api_key=key,
        base_url=BASE_URLS[provider], _provider_name=provider, **kwargs,
    )


# ── 模型路由（DB 驱动 + 备用降级）───────────────────────────

_route_cache: dict[tuple[str, str], list[tuple[str, str, bool, int]]] = {}
_cache_initialized = False


def _load_model_route_cache():
    """从 DB 读取 ModelRoute 配置到缓存。已加载则跳过。"""
    global _route_cache, _cache_initialized
    if _cache_initialized:
        return
    try:
        from api.utils.db import postgreSQL_URL
        import psycopg

        with psycopg.connect(postgreSQL_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT role, "serviceType", provider, "modelName", "isBackup", priority
                       FROM "ModelRoute" WHERE "isActive" = true
                       ORDER BY role, "serviceType", "isBackup" ASC, priority ASC"""
                )
                rows = cur.fetchall()
        cache = {}
        for role, st, prov, model, backup, pri in rows:
            cache.setdefault((role, st), []).append((prov, model, backup, pri))
        _route_cache = cache
        _cache_initialized = True
        print(f"[models] 模型路由已加载：{len(rows)} 条记录")
    except Exception as exc:
        print(f"[models] 加载模型路由失败: {exc}")


def create_model_with_fallback(
    role: str, service_type: str = "novel", temperature: float = 0.3, **kwargs: Any,
) -> ChatOpenAI:
    """查 DB 模型路由创建主模型（isBackup=false）；无配置时返回 None。"""
    _load_model_route_cache()
    configs = _route_cache.get((role, service_type), [])

    if not configs:
        return None

    primary = [c for c in configs if not c[2]]
    if not primary:
        return None

    provider, model_name, _backup, _pri = sorted(primary, key=lambda c: c[3])[0]
    return create_chat_model(provider, model_name, temperature=temperature, **kwargs)


def create_backup_model(
    role: str, service_type: str = "novel", temperature: float = 0.3, **kwargs: Any,
) -> ChatOpenAI:
    """查 DB 创建备用模型；无显式备用时降级为主模型（同厂商同名），保证 fallback 链路不空。"""
    _load_model_route_cache()
    configs = _route_cache.get((role, service_type), [])

    backups = sorted([c for c in configs if c[2]], key=lambda c: c[3])
    if backups:
        provider, model_name, _backup, _pri = backups[0]
        return create_chat_model(provider, model_name, temperature=temperature, **kwargs)

    # 无显式备用：用主模型充当备用，至少让 ainvoke_with_fallback 有重试机会
    primary = sorted([c for c in configs if not c[2]], key=lambda c: c[3])
    if primary:
        provider, model_name, _backup, _pri = primary[0]
        return create_chat_model(provider, model_name, temperature=temperature, **kwargs)

    return None


# ── 公开模型工厂 ─────────────────────────────────────────────

def MainModel(service_type: str = "novel", temperature: float = 0.3, **kwargs: Any):
    return create_model_with_fallback("main", service_type, temperature=temperature, **kwargs)

def IntentModel(service_type: str = "novel", temperature: float = 0.3, **kwargs: Any):
    return create_model_with_fallback("intent", service_type, temperature=temperature, **kwargs)

def CompressModel(service_type: str = "novel", temperature: float = 0.3, **kwargs: Any):
    return create_model_with_fallback("compress", service_type, temperature=temperature, **kwargs)

# ── 备用模型工厂 ─────────────────────────────────────────────

def BackupMainModel(service_type: str = "novel", temperature: float = 0.3, **kwargs: Any):
    return create_backup_model("main", service_type, temperature=temperature, **kwargs)

def BackupIntentModel(service_type: str = "novel", temperature: float = 0.1, **kwargs: Any):
    return create_backup_model("intent", service_type, temperature=temperature, **kwargs)

def BackupCompressModel(service_type: str = "novel", temperature: float = 0.1, **kwargs: Any):
    return create_backup_model("compress", service_type, temperature=temperature, **kwargs)

def BackupChatModel(service_type: str = "novel", temperature: float = 0.7, **kwargs: Any):
    return create_backup_model("main", service_type, temperature=temperature, **kwargs)


# ── 调用层故障转移辅助函数 ─────────────────────────────────

async def ainvoke_with_fallback(primary, backup, *args, **kwargs):
    """优先调主模型的 ainvoke，失败后降级到备用模型；都失败则抛异常。"""
    try:
        return await primary.ainvoke(*args, **kwargs)
    except Exception as exc:
        print(f"[fallback] 主模型调用失败: {exc}，尝试备用模型")
        if backup is not None:
            try:
                return await backup.ainvoke(*args, **kwargs)
            except Exception as exc2:
                print(f"[fallback] 备用模型也失败: {exc2}")
        raise


def invoke_with_fallback(primary, backup, *args, **kwargs):
    """同步版：优先调主模型的 invoke，失败后降级到备用模型。"""
    try:
        return primary.invoke(*args, **kwargs)
    except Exception as exc:
        print(f"[fallback] 主模型同步调用失败: {exc}，尝试备用模型")
        if backup is not None:
            try:
                return backup.invoke(*args, **kwargs)
            except Exception as exc2:
                print(f"[fallback] 备用模型同步也失败: {exc2}")
        raise


def RerankModel(
    query: str,
    documents: list[str],
    top_n: int = 5,
    timeout: int = 30,
) -> list[tuple[int, float]]:
    """交叉编码器重排（SiliconFlow），返回已按 relevance_score 降序的 [(index, score)]。"""
    key = os.getenv("SILICONFLOW_API_KEY")
    if not key:
        raise ValueError("缺少 SILICONFLOW_API_KEY")

    import requests
    resp = requests.post(
        "https://api.siliconflow.cn/v1/rerank",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": "BAAI/bge-reranker-v2-m3", "query": query,
            "documents": documents, "top_n": top_n, "return_documents": False,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return [(r["index"], r["relevance_score"]) for r in resp.json()["results"]]


# ── JSON 解析工具 ────────────────────────────────────────────

def parse_json_value(text: Any) -> Any:
    """从模型文本里取出第一个完整的 JSON 值（对象或数组），容忍 ```json 围栏与前后解释。

    DeepSeek V4 默认开启 thinking 时拒绝 tool_choice 与 response_format，
    结构化输出只能靠提示词约束 + 自行解析。
    """
    if not isinstance(text, str):
        text = str(text)
    s = text.strip()
    if s.startswith("```"):
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
    value = parse_json_value(text)
    if not isinstance(value, dict):
        raise ValueError(f"模型输出不是 JSON 对象：{text[:200]!r}")
    return value