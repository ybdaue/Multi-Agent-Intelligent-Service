"""法律文档风险分析 — RAG + LLM 分析主流程（langgraph 编排）

接收 file_id，分页读取文档切片并检索相关法条（retrieve_chunk 批量 top5，法条文本经
retrieve_law 同一格式化出口），按输入预算分批并发提交 LLM 分析风险，最后由 consolidation
去重归并后输出。
"""

import json
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict
from pydantic import BaseModel, Field

from langgraph.graph import StateGraph, START, END
from langchain_core.tools import tool

from agents.utils.models import MainModel
from ..tools.retrieve_law import format_law_hits, search_law_text


# 阶段一：切片风险扫描（支持多切片合并为一批，减少 LLM 调用次数）

class BatchRiskItem(BaseModel):
    """批量扫描中，单个风险点（带切片归属）"""
    chunk_index: int = Field(description="风险所属切片编号，对应输入中的【切片x】，禁止编造")
    risk_type: str = Field(description="风险类型，仅限以下枚举值：违约责任缺陷、管辖条款不利、权利义务不对等、免责条款过宽、争议解决条款缺失、法律法规引用过时、送达条款缺失、表述模糊、期限约定不明、其他")
    risk_level: str = Field(description="风险等级：high / medium / low")
    sentence: str = Field(description="原文中存在风险的句子或条款，尽量保留原文表述")
    issue: str = Field(description="具体风险说明，指出问题所在")
    suggestion: str = Field(description="修改建议")
    legal_basis: str = Field(description="法律依据，引用具体法条原文")


class BatchRiskPage(BaseModel):
    """一个批量（多个切片）的分析结果"""
    risks: list[BatchRiskItem] = Field(description="该批次所有切片中发现的全部风险点，无风险时返回空数组")


BATCH_SCAN_PROMPT = """你是一位资深法律风险审查专家。下面给出同一文件中的多段文本切片，请逐段审查其中的法律风险。

## 文本切片（每段带【切片x】编号）
{chunks_block}

## 审查要求
1. 逐段识别每段切片中所有可能的法律风险点
2. 对每个风险点给出具体说明、引用具体的法律条款、给出修改建议
3. 每个风险点必须标注它属于哪一段切片（chunk_index 对应【切片x】的编号）

## 风险类型（仅限以下枚举值）
- 违约责任缺陷：违约金约定不明、赔偿范围不清等
- 管辖条款不利：管辖法院约定对己方不利
- 权利义务不对等：单方加重对方责任、排除对方主要权利
- 免责条款过宽：免责范围过大，可能被认定无效
- 争议解决条款缺失：未约定仲裁/诉讼方式
- 法律法规引用过时：引用的法律已被废止或修订
- 送达条款缺失：未约定有效送达方式
- 表述模糊：条款存在歧义或表述不清晰
- 期限约定不明：履行期限、付款期限等不明确
- 其他：不属于上述类型的风险

## 风险等级
- high：可能导致重大经济损失或法律后果
- medium：存在一定风险，建议修改
- low：建议完善，但不紧急

## 输出约束
- 只输出风险点，没有风险时返回空数组
- 每个风险点必须包含 legal_basis 和 chunk_index
- chunk_index 只能使用【切片x】中出现的编号，禁止编造
- risk_level 必须严格为 high / medium / low 之一
- risk_type 必须使用上述枚举值
- 禁止输出任何解释性文字
- 所有风险点描述、建议必须使用中文"""


# 阶段二：全报告 consolidation（去重 + 归并 + 整体评估）

class ConsolidatedRisk(BaseModel):
    """归并后的风险点"""
    risk_type: str
    risk_level: str
    sentence: str
    issue: str
    suggestion: str
    legal_basis: str
    affected_chunks: list[int] = Field(description="出现该风险的切片索引列表")


class ConsolidatedReport(BaseModel):
    """最终结构化的风险报告"""
    summary: str = Field(description="文档整体风险评估摘要（2-3句话概括）")
    risk_score: str = Field(description="文档整体风险评分：high / medium / low")
    risks: list[ConsolidatedRisk]


CONSOLIDATE_PROMPT = """你是一位资深法律风险审查专家。下面是逐条分析法律合同后得到的原始风险列表（未去重）。

请执行以下操作：
1. **去重合并**：将描述同一风险的不同条目合并为一个，保留最完整的表述
2. **跨条款识别**：如果同一类风险出现在多个 chunk 中，标记所有 affected_chunks
3. **整体评估**：给出文档的整体风险评分和摘要

# 原始风险列表（JSON）
{raw_risks_json}

# 总切片数
{total_chunks}

# 规则
- 合并标准：相同 risk_type + 描述同一法律问题 → 合并
- risk_level 取合并项中的最高等级
- affected_chunks 列出所有出现该风险的 chunk_index
- risk_score：high（3个以上 high 风险或1个致命问题）、medium（有 medium 风险）、low（仅有少量 low 风险或无风险）
- summary：指出文档存在的主要法律问题领域和整体风险水平

# 输出约束
- 禁止输出任何解释性文字
- 只输出结构化 JSON
- summary、风险描述必须使用中文"""


# LLM 实例（各阶段独立模型实例，温度不同）
_scan_batch_model = MainModel(temperature=0.1).with_structured_output(BatchRiskPage)
_consolidate_model = MainModel(temperature=0.1).with_structured_output(ConsolidatedReport)

# 批间并发线程数：减少墙钟时间
SCAN_WORKERS = 4
# 内存上界：每页最多从 RAG 取回的切片数（文本+embedding 随页释放，大文件不一次性全量载入）
# 取值保证一页切片数 ≥ 并发数×批内上限，让线程池在页内保持满载
PAGE_SIZE = 30
# 单次 LLM 调用的内容预算（字符）：多个切片按此合并成一批，防止超出模型最大输入量
# parse.py 已保证切片正文 ≤ 700 字（DEFAULT_CHUNK_SIZE），单切片成本以法条为主，预算可适当放大
MAX_BATCH_CHARS = 10000
# 单批最多切片数：限制单次调用的输出复杂度，避免风险归因混乱
MAX_BATCH_CHUNKS = 5
# 每个用户切片法律依据展开的父模块上限（父文本较肥，取前几块保整父语义即可）
LAW_PARENT_PER_CHUNK = 2
# 原始风险点不超过该数量时，跳过 LLM 归并，用代码直接汇总（省一次 LLM 调用约 20~25s）
CONSOLIDATE_MIN_RISKS = 5


# langgraph state 与核心分析逻辑

class AnalyseState(TypedDict, total=False):
    file_id: str
    total_chunks: int
    raw_risks: list[dict]
    result: dict


def _chunk_law_context(chunk: dict, batch_laws: list[dict], allow_supplement: bool = False) -> str:
    """单个切片的法律依据块：批量检索结果优先；批量无结果时用 retrieve_law 文本检索补一次。"""
    if batch_laws:
        return format_law_hits(batch_laws)
    if allow_supplement:
        text = search_law_text(chunk["content"])
        if "[来源:" in text:
            return text
    return "（未检索到直接相关的法律条文，请基于法律常识判断。）"


def _group_into_batches(chunks: list[dict], law_results: list[list[dict]]) -> list[list[tuple[dict, str]]]:
    """把切片按输入预算（MAX_BATCH_CHARS）和批内上限（MAX_BATCH_CHUNKS）合并成若干批。

    每批元素为 (chunk, legal_context)。单个超大切片单独成批，保证不超模型输入上限。
    """
    # 整页批量检索全部为空 → 法律库当前无可命中内容，跳过逐片补充检索，避免 N 次无效查询
    has_hits = any(bool(lr) for lr in law_results)
    batches: list[list[tuple[dict, str]]] = []
    current: list[tuple[dict, str]] = []
    current_size = 0
    for i, chunk in enumerate(chunks):
        laws = law_results[i] if i < len(law_results) else []
        legal_context = _chunk_law_context(chunk, laws, allow_supplement=has_hits)
        size = len(chunk["content"]) + len(legal_context)
        if current and (current_size + size > MAX_BATCH_CHARS or len(current) >= MAX_BATCH_CHUNKS):
            batches.append(current)
            current = []
            current_size = 0
        current.append((chunk, legal_context))
        current_size += size
    if current:
        batches.append(current)
    return batches


def _build_chunks_block(batch: list[tuple[dict, str]]) -> str:
    """把一批切片（含各自法条依据）拼成【切片x】格式的提示词块。"""
    parts = []
    for chunk, legal_context in batch:
        parts.append(
            f"【切片{chunk['metadata']['chunk_index']}】\n"
            f"{chunk['content']}\n\n"
            f"相关法律依据：\n{legal_context}"
        )
    return "\n\n".join(parts)


def _scan_batch(batch: list[tuple[dict, str]]) -> list[dict]:
    """对一批切片调用 LLM 扫描风险，返回带 chunk_index 的风险条目列表（失败返回空）。

    返回前校验 chunk_index 必须属于本批切片，剔除模型编造的编号。
    """
    valid_indexes = {chunk["metadata"]["chunk_index"] for chunk, _ in batch}
    try:
        res = _scan_batch_model.invoke([
            BATCH_SCAN_PROMPT.format(chunks_block=_build_chunks_block(batch))
        ])
        return [
            {
                "chunk_index": item.chunk_index,
                "risk_type": item.risk_type,
                "risk_level": item.risk_level,
                "sentence": item.sentence,
                "issue": item.issue,
                "suggestion": item.suggestion,
                "legal_basis": item.legal_basis,
            }
            for item in res.risks
            if item.chunk_index in valid_indexes
        ]
    except Exception:
        return []


def _load_node(state: AnalyseState) -> dict:
    from agents.utils.RAG import get_chunk_num

    total = get_chunk_num(state["file_id"])
    if total == 0:
        return {
            "total_chunks": 0,
            "result": {"error": "该文件已过期或无切片数据，请重新上传文件后再试。"},
        }
    return {"total_chunks": total}


def _scan_node(state: AnalyseState) -> dict:
    from agents.utils.RAG import get_chunk, retrieve_chunk, expand_to_parents

    file_id = state["file_id"]
    total = state["total_chunks"]
    raw_risks: list[dict] = []

    # 分页取回（内存上界 PAGE_SIZE）+ 分批并发扫描：
    # 每页至多 PAGE_SIZE 个切片（含 embedding，随页释放，大文件不全量载入）；
    # 页内按输入预算合并成批，批间并发调用 LLM 缩短墙钟时间。
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        for page in range(1, pages + 1):
            chunks = get_chunk(file_id, page=page, limit=PAGE_SIZE)
            if not chunks:
                break

            try:
                raw_law = retrieve_chunk(chunks)
                # 法条命中子→父展开：给 LLM 的是整段父模块（父文本偏肥，逐块限 2 个父，避免超预算）
                law_results = [
                    expand_to_parents(res, limit=LAW_PARENT_PER_CHUNK) if res else res
                    for res in raw_law
                ]
            except Exception:
                law_results = []

            batches = _group_into_batches(chunks, law_results)
            for risks in pool.map(_scan_batch, batches):
                raw_risks.extend(risks)

    return {"raw_risks": raw_risks}


def _route_after_scan(state: AnalyseState) -> str:
    if len(state.get("raw_risks", [])) <= CONSOLIDATE_MIN_RISKS:
        return "summarize"
    return "consolidate"


def _summarize_node(state: AnalyseState) -> dict:
    """少量风险/无风险时跳过 LLM 归并，用代码直接汇总，省一次 LLM 调用（约 20~25s）。"""
    file_id = state["file_id"]
    total = state["total_chunks"]
    raw = state.get("raw_risks", [])

    if not raw:
        return {
            "result": {
                "file_id": file_id,
                "total_chunks": total,
                "risk_score": "low",
                "summary": "未发现明显法律风险。",
                "total_risks": 0,
                "risks": [],
            }
        }

    order = {"high": 3, "medium": 2, "low": 1}
    risk_score = max(raw, key=lambda r: order.get(r["risk_level"], 0))["risk_level"]
    return {
        "result": {
            "file_id": file_id,
            "total_chunks": total,
            "risk_score": risk_score,
            "summary": f"共发现 {len(raw)} 处风险点，整体风险等级为{risk_score}。",
            "total_risks": len(raw),
            "risks": [{**r, "affected_chunks": [r["chunk_index"]]} for r in raw],
        }
    }


def _consolidate_node(state: AnalyseState) -> dict:
    """LLM 归并去重 + 整体评估；失败时降级返回原始扫描结果。"""
    file_id = state["file_id"]
    total = state["total_chunks"]
    raw = state.get("raw_risks", [])

    try:
        consolidated = _consolidate_model.invoke([
            CONSOLIDATE_PROMPT.format(
                raw_risks_json=json.dumps(raw, ensure_ascii=False),
                total_chunks=total,
            )
        ])
        return {
            "result": {
                "file_id": file_id,
                "total_chunks": total,
                "risk_score": consolidated.risk_score,
                "summary": consolidated.summary,
                "total_risks": len(consolidated.risks),
                "risks": [r.model_dump() for r in consolidated.risks],
            }
        }
    except Exception as e:
        print(f"[analyze_file] consolidation 失败，降级返回原始结果: {e}")
        return {
            "result": {
                "file_id": file_id,
                "total_chunks": total,
                "risk_score": "unknown",
                "summary": "归并分析失败，以下为原始扫描结果。",
                "total_risks": len(raw),
                "risks": raw,
            }
        }


def _after_load(state: AnalyseState) -> str:
    return END if state.get("result") else "scan"


_analyse_graph = StateGraph(AnalyseState)
_analyse_graph.add_node("load", _load_node)
_analyse_graph.add_node("scan", _scan_node)
_analyse_graph.add_node("summarize", _summarize_node)
_analyse_graph.add_node("consolidate", _consolidate_node)
_analyse_graph.add_edge(START, "load")
_analyse_graph.add_conditional_edges("load", _after_load)
_analyse_graph.add_conditional_edges(
    "scan",
    _route_after_scan,
    {"summarize": "summarize", "consolidate": "consolidate"},
)
_analyse_graph.add_edge("summarize", END)
_analyse_graph.add_edge("consolidate", END)
_analyse_graph = _analyse_graph.compile(name="analyse_subagent")


def analyze_file(file_id: str) -> dict:
    """对指定 file_id 的文档进行全量法律风险分析。

    由 langgraph 编排：load(切片计数) → scan(分页取回+批量检索法条+分批并发扫描) →
    summarize(少量/无风险直接汇总) 或 consolidate(LLM 归并) → 输出最终报告。
    """
    final = _analyse_graph.invoke(
        {"file_id": file_id, "total_chunks": 0, "raw_risks": [], "result": {}}
    )
    return final.get("result") or {"error": "分析失败，请稍后重试。"}


class AnalyzerAgent:
    """保持与 legal/__init__.py 中 AnalyzerAgent.analyze() 调用的兼容。"""

    @staticmethod
    def analyze(file_id: str) -> dict:
        return analyze_file(file_id)


@tool
def analyze_document(file_id: str) -> dict:
    """分析法律文档中的法律风险。

    接收已上传文档的 file_id，调用 RAG 分析流程，
    返回包含风险点、风险等级、修改建议、法律依据的结构化报告。

    Args:
        file_id: 用户上传文档的 file_id
    """
    print("分析工具被调用了")
    return analyze_file(file_id)
