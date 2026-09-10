"""法律依据检索工具 — 从静态法律库取回法条父模块整段。

供 legal agent 在自判"法律依据不足"时调用，把相关法条原文取回作为证据。

检索采用多路召回：向量检索（Chroma laws_docs 子模块）+ BM25 关键词检索
（Postgres bm25 表子模块）经 RRF（Reciprocal Rank Fusion）融合，再用交叉编码器
（bge-reranker-v2-m3）在子模块上重排；命中的子随后展开为其所属**父模块整段**
（父文本存 PG laws 表）返回给调用方，还原整章/条群组上下文。不含用户上传文件。
"""

from langchain_core.tools import tool

from agents.utils.RAG import retrieve_text, expand_to_parents
from agents.utils.models import RerankModel
from agents.utils import bm25_index

# 单次取回条数（内部固定，不入工具 schema）
TOP_K = 6
# 各召回路取回池大小（供融合），远大于最终输出 TOP_K
RECALL_POOL = 12
# 最终返回的父模块块数（父更"肥"，故比原 TOP_K 略少）
PARENT_RETURN_K = 4
# RRF 融合常数
RRF_K = 60


def format_law_hits(hits: list[dict]) -> str:
    """把检索结果列表拼成带来源标注的文本。

    各子代理共用此函数作为唯一法条文本出口，保证与 retrieve_law 工具返回格式一致。
    """
    parts = []
    for r in hits:
        heading = r["metadata"].get("heading", "法律法规")
        line = f"[来源: {heading}]\n{r['content']}"
        if r.get("distance") is not None:
            line += f"\n(相似度 {r['distance']:.4f})"
        parts.append(line)
    return "\n\n".join(parts)


def _chunk_id(r: dict) -> str:
    """从检索结果取稳定标识：BM25 条目用 chunk_id，向量条目用 metadata 拼 chunk_id。"""
    if r.get("chunk_id"):
        return r["chunk_id"]
    meta = r.get("metadata") or {}
    if meta.get("file_id") is not None and meta.get("chunk_index") is not None:
        return f"{meta['file_id']}_{meta['chunk_index']}"
    # 退化兜底：以内容全文作标识
    return r.get("content", "")


def _bm25_hits_to_std(hits: list[dict]) -> list[dict]:
    """把 BM25 条目转成与向量路一致的结构，便于融合与格式化。"""
    return [
        {
            "content": r["content"],
            "metadata": {
                "heading": r.get("heading"),
                "file_id": r.get("file_id"),
                "chunk_index": r.get("chunk_index"),
                "parent_index": r.get("parent_index"),
            },
            "distance": None,
            "chunk_id": r["chunk_id"],
            "bm25_score": r["bm25_score"],
            "file_id": r.get("file_id"),
            "parent_index": r.get("parent_index"),
        }
        for r in hits
    ]


def _fuse_rrf(vector_hits: list[dict], bm25_hits: list[dict]) -> list[dict]:
    """RRF 融合两路结果：按 chunk_id 对齐，score = sum(1/(k + rank))。

    只有一路命中时等价于该路的排序。
    """
    def _ranked(items):
        return {_chunk_id(r): rank for rank, r in enumerate(items, start=1)}

    vec_ranks = _ranked(vector_hits)
    bm25_ranks = _ranked(bm25_hits)

    fused: dict[str, dict] = {}
    for r in list(vector_hits) + list(bm25_hits):
        cid = _chunk_id(r)
        if cid not in fused:
            fused[cid] = r
        fused[cid].setdefault("rrf_score", 0.0)
        if cid in vec_ranks:
            fused[cid]["rrf_score"] += 1.0 / (RRF_K + vec_ranks[cid])
        if cid in bm25_ranks:
            fused[cid]["rrf_score"] += 1.0 / (RRF_K + bm25_ranks[cid])

    fused_list = list(fused.values())
    fused_list.sort(key=lambda r: r["rrf_score"], reverse=True)
    return fused_list


def _rerank_candidates(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """用交叉编码器对融合候选重排；失败时降级返回候选本身前 top_k。"""
    docs = [c["content"] for c in candidates]
    try:
        ranked = RerankModel(query, docs, top_n=top_k)
    except Exception as e:
        print(f"rerank 失败，降级返回融合结果: {e}")
        return candidates[:top_k]

    # ranked 为 [(index, score), ...]，已按 score 降序
    ordered = []
    for i, s in ranked:
        r = candidates[i]
        r["rerank_score"] = s
        ordered.append(r)
    return ordered[:top_k]


def _retrieve_fused(query: str, top_k: int = TOP_K) -> list[dict]:
    """多路召回：向量 + BM25 → RRF 融合 → 交叉编码器重排 → 子命中展开为父模块。

    检索对齐仍发生在**子模块**上（子短、精确）；最终返回的是子命中所属**父模块整段**
    （还原整章/条群组上下文）。任一回路异常/为空时其余路独立兜底。
    返回结构：[{content, metadata, distance, chunk_id, parent_id}]（父模块），
    content 是父全文（内嵌条号）。
    """
    query = query.strip()

    # 路1：向量检索（子命中）
    try:
        vector_hits = retrieve_text(query, top_k=RECALL_POOL) or []
    except Exception as e:
        print(f"向量检索失败: {e}")
        vector_hits = []

    # 路2：BM25 关键词检索（子命中）
    try:
        raw_bm25 = bm25_index.search(query, top_k=RECALL_POOL)
        bm25_hits = _bm25_hits_to_std(raw_bm25)
    except Exception as e:
        print(f"BM25 检索失败: {e}")
        bm25_hits = []

    # 两路都失败 → 无命中
    if not vector_hits and not bm25_hits:
        return []

    fused = _fuse_rrf(vector_hits, bm25_hits)
    # 在子模块上重排（池取大些，跨更多父块），再把命中的子展开回父
    rerank_pool = max(top_k, PARENT_RETURN_K * 2)
    ordered = _rerank_candidates(query, fused, rerank_pool)

    try:
        expanded = expand_to_parents(ordered, limit=PARENT_RETURN_K)
        if expanded:
            return expanded
    except Exception as e:
        print(f"展开父模块失败，退回子命中: {e}")
    return ordered[:top_k]


def search_law_text(query: str, top_k: int = TOP_K) -> str:
    """检索法条并格式化为文本；命中返回 [来源:...] 文本，未命中/异常返回提示语。"""
    if not query or not query.strip():
        return "请输入要检索的法律关键词或完整问题。"

    try:
        hits = _retrieve_fused(query.strip(), top_k=top_k)
    except Exception as e:
        return f"法律检索失败: {e}"

    if not hits:
        return "未检索到直接相关的法律依据，建议基于法律常识判断，或提示用户咨询执业律师。"

    return format_law_hits(hits)


@tool
def retrieve_law_basis(query: str) -> str:
    """在法律法规库中检索与问题相关的法条原文，返回带来源标注的文本。

    当手头法律依据不足、对某个法律问题没有把握、或起草/分析时需要引用具体法条时，
    从静态法律库取回法条作为证据。

    Args:
        query: 需要检索的法律关键词或完整问题（如"违约金的上限规定"）
    """
    return search_law_text(query, top_k=TOP_K)
