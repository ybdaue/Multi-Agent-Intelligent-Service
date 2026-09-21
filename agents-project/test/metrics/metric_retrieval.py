"""检索召回率 —— Recall@k / MRR，并做「向量 → BM25 → RRF → rerank」四组消融对照。

为什么要做消融：单路向量对法条编号、专有名词类查询召回差，这是当初加 BM25 与 rerank 的
动机。只有把四组配置放在同一个标注集上对比，才能证明"每一步分别值多少"，而不是凭感觉说优化了。

指标口径：
    Recall@k   返回的 k 个父块中至少有一个命中期望的 case 占比
               （期望 = retrieval_keywords 任一出现，或 expect_parent_ids 任一命中）
    MRR        首个命中父块排名的倒数，对"命中但排得靠后"更敏感
    平均时延    四组各自的时延（按组成步骤归因，避免重复调用 rerank 产生额外费用）

数据库安全：本文件只读 Chroma / PG（向量查询 + legal_bm25 表读取 + legal_laws 父表 SELECT），
    不写入任何表，也不调用 delete_expired_chunks。

用法（在 agents-project 目录下，需先起 Chroma:8000、PG，并备好本地 embedding 模型）：
    python test/metrics/metric_retrieval.py
    python test/metrics/metric_retrieval.py --save
    python test/metrics/metric_retrieval.py --from-corpus 30   # 从 legal_laws 表自动构造精确标注
"""

import random
import sys
import time
from pathlib import Path

_METRICS_DIR = Path(__file__).resolve().parent
if str(_METRICS_DIR) not in sys.path:
    sys.path.insert(0, str(_METRICS_DIR))

import _common as C  # noqa: E402

CONFIGS = [
    ("vector", "仅向量"),
    ("bm25", "仅 BM25"),
    ("rrf", "RRF 融合（向量+BM25）"),
    ("rerank", "RRF + 交叉编码器重排（线上完整链路）"),
]


def build_parser():
    p = C.arg_parser("检索召回率（多路消融）")
    p.add_argument(
        "--from-corpus",
        type=int,
        default=0,
        metavar="N",
        help="从 PG legal_laws 表抽样 N 条构造精确 parent_id 标注（用于校验召回链路对齐）",
    )
    return p


def load_corpus_cases(n: int, seed: int = 42) -> list[dict]:
    """从 PG legal_laws 父表抽样构造精确标注（expect_parent_ids）。

    这是**召回链路对齐检查**，不是语义质量评测：query 取自父文本中段，与目标父块高度重叠，
    四组配置理应接近满分。语义质量请看标注集里带 retrieval_keywords 的那组 case。
    """
    import psycopg

    from agents.utils.law_parent_store import LAWS_TABLE, postgreSQL_URL

    with psycopg.connect(postgreSQL_URL) as conn:
        rows = conn.execute(
            f"SELECT parent_id, content FROM {LAWS_TABLE} "
            "WHERE content IS NOT NULL AND length(content) > 160"
        ).fetchall()

    if not rows:
        raise SystemExit("legal_laws 表没有可用数据：先跑 python agents/utils/legal_ingest.py 导入法规。")

    picks = random.Random(seed).sample(rows, min(n, len(rows)))
    cases = []
    for parent_id, content in picks:
        snippet = content.strip()[60:110].strip() or content.strip()[:50]
        cases.append(
            {
                "id": f"corpus-{parent_id}",
                "query": snippet,
                "expect_parent_ids": [parent_id],
                "retrieval_keywords": [],
            }
        )
    return cases


def _hit_rank(parents: list[dict], case: dict) -> int | None:
    """返回首个命中父块的 1-based 排名；未命中返回 None。"""
    expected_ids = set(case.get("expect_parent_ids") or [])
    keywords = [k for k in (case.get("retrieval_keywords") or []) if k]
    for rank, parent in enumerate(parents, start=1):
        if expected_ids:
            cid = parent.get("chunk_id") or parent.get("parent_id")
            if cid in expected_ids:
                return rank
        if keywords and any(k in (parent.get("content") or "") for k in keywords):
            return rank
    return None


def collect(cases: list[dict], RL, bm25_index, expand_to_parents, retrieve_text) -> dict:
    """逐条查询，四组配置复用同一份向量/BM25 中间结果（rerank 只调用一次）。"""
    return_k = RL.PARENT_RETURN_K
    pool = max(RL.TOP_K, return_k * 2)

    stats = {name: {"latencies": [], "ranks": []} for name, _ in CONFIGS}

    for i, case in enumerate(cases, start=1):
        query = case["query"]
        print(f"  [{i}/{len(cases)}] {query[:36]}")

        t0 = time.perf_counter()
        vec_children = retrieve_text(query, top_k=RL.RECALL_POOL) or []
        t_vec = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        bm25_std = RL._bm25_hits_to_std(bm25_index.search(query, top_k=RL.RECALL_POOL) or [])
        t_bm25 = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        fused = RL._fuse_rrf(vec_children, bm25_std) if (vec_children or bm25_std) else []
        t_fuse = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        reranked = RL._rerank_candidates(query, fused, pool) if fused else []
        t_rerank = (time.perf_counter() - t0) * 1000

        results: dict[str, tuple[list[dict], float]] = {}

        t0 = time.perf_counter()
        results["vector"] = (
            expand_to_parents(vec_children, limit=return_k) if vec_children else [],
            t_vec + (time.perf_counter() - t0) * 1000,
        )

        t0 = time.perf_counter()
        results["bm25"] = (
            expand_to_parents(bm25_std, limit=return_k) if bm25_std else [],
            t_bm25 + (time.perf_counter() - t0) * 1000,
        )

        t0 = time.perf_counter()
        results["rrf"] = (
            expand_to_parents(fused[:pool], limit=return_k) if fused else [],
            t_vec + t_bm25 + t_fuse + (time.perf_counter() - t0) * 1000,
        )

        t0 = time.perf_counter()
        try:
            rr_parents = expand_to_parents(reranked, limit=return_k) if reranked else []
        except Exception as e:
            print(f"      展开父模块失败，退回子命中：{e}")
            rr_parents = reranked[: RL.TOP_K]
        # 线上 _retrieve_fused 就是这条路径：融合 → 重排 → 展开（失败降级为子命中）
        results["rerank"] = (
            rr_parents,
            t_vec + t_bm25 + t_fuse + t_rerank + (time.perf_counter() - t0) * 1000,
        )

        for name, (parents, latency) in results.items():
            stats[name]["latencies"].append(latency)
            stats[name]["ranks"].append(_hit_rank(parents, case))

    return stats


def report(cases: list[dict], stats: dict, args, return_k: int) -> None:
    total = len(cases)
    C.header(f"检索召回率（Recall@{return_k}）与四组消融对照")
    print(f"标注 case 数：{total}   来源：{'legal_laws 表自动构造（链路对齐）' if args.from_corpus else '标注集'}")
    print()
    print(f"  {'配置':<32}{'Recall@k':>16}{'MRR':>10}{'平均时延':>12}")
    print("  " + "-" * 68)

    summary = {}
    for name, label in CONFIGS:
        ranks = stats[name]["ranks"]
        hits = sum(1 for r in ranks if r is not None)
        mrr = sum(1.0 / r for r in ranks if r is not None) / total if total else 0.0
        lat = C.percentiles(stats[name]["latencies"])
        print(
            f"  {label:<32}{C.pct(hits, total):>16}{mrr:>10.3f}"
            f"{(str(lat['avg']) + ' ms'):>12}"
        )
        summary[name] = {
            "label": label,
            "recall_at_k": round(hits / total, 4) if total else None,
            "mrr": round(mrr, 4),
            "avg_latency_ms": lat["avg"],
            "misses": [
                {"case_id": c["id"], "query": c["query"]}
                for c, r in zip(cases, ranks)
                if r is None
            ],
        }

    print("\n逐步增量（相对上一组，Recall@k 的绝对提升）：")
    names = [n for n, _ in CONFIGS]
    for prev, cur in zip(names, names[1:]):
        delta = summary[cur]["recall_at_k"] - summary[prev]["recall_at_k"]
        print(f"  {summary[prev]['label']:<32} → {summary[cur]['label']:<32} {delta:+.1%}")

    worst = max(names, key=lambda n: len(summary[n]["misses"]))
    misses = summary[worst]["misses"]
    if misses:
        print(f"\n未命中明细（以最差配置「{summary[worst]['label']}」为准，{len(misses)} 条）：")
        for m in misses:
            print(f"  [{m['case_id']}] {m['query'][:40]}")
    else:
        print("\n四组配置均全部命中。")

    if args.save:
        path = C.save_result(
            f"retrieval_{'corpus' if args.from_corpus else 'evalset'}",
            {
                "metric": "retrieval_recall",
                "k": return_k,
                "n": total,
                "source": "corpus" if args.from_corpus else "eval_set",
                "configs": summary,
            },
        )
        print(f"\n结果已写入：{path}")


def main(args) -> None:
    C.bootstrap()

    if args.from_corpus:
        cases = load_corpus_cases(args.from_corpus)
        print(f"从 legal_laws 表自动构造 {len(cases)} 条精确标注 case")
    else:
        cases = [
            c
            for c in C.load_cases()
            if c.get("retrieval_keywords") or c.get("expect_parent_ids")
        ]
    cases = C.select(cases, args)

    import agents.legal.tools.retrieve_law as RL
    from agents.utils import bm25_index
    from agents.utils.RAG import expand_to_parents, init, is_ready, retrieve_text

    init()
    if not is_ready():
        raise SystemExit(
            "RAG 未就绪：确认 Docker 里 Chroma 跑在 localhost:8000，且本地 embedding 模型存在于 "
            "agents-project/models/bge-large-zh-v1.5。否则检索结果全为空，指标没有参考价值。"
        )
    if not bm25_index.init():
        print("⚠️  BM25 索引未就绪（legal_bm25 表为空或 PG 不可用）：仅 BM25 / RRF / rerank 三组会退化。")
    else:
        print(f"BM25 索引就绪，共 {len(bm25_index._docs)} 条")

    print(
        f"配置：RECALL_POOL={RL.RECALL_POOL} TOP_K={RL.TOP_K} "
        f"PARENT_RETURN_K={RL.PARENT_RETURN_K} RRF_K={RL.RRF_K}\n"
        f"待测 {len(cases)} 条查询（四组配置共用中间结果，rerank 只调用一次）\n"
    )

    stats = collect(cases, RL, bm25_index, expand_to_parents, retrieve_text)
    report(cases, stats, args, RL.PARENT_RETURN_K)


if __name__ == "__main__":
    main(build_parser().parse_args())
