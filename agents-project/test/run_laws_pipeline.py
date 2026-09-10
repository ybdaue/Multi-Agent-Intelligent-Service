"""端到端验证：父子切分 → 子入 Chroma/bm25 + 父入 PG laws → 子检索、父返回。

用法（agents-project 下，venv 内）：
    python test/run_laws_pipeline.py

无论流程成功或失败，脚本结束前都会把本用例写入数据库的 sample_law_001 数据清空
（Chroma laws_docs 子切片 + Postgres bm25 子行 + Postgres laws 父行），可反复重跑。
"""
import importlib.util
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "agents" / "utils"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FILE_ID = "sample_law_001"


def _load(name: str, fn: str):
    spec = importlib.util.spec_from_file_location(name, PKG / fn)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cleanup_store(RAG, parent_store, legal_ingest, file_id: str) -> None:
    """删除 file_id 写进三个库的全部测试数据。每库独立容错，失败仅告警不阻断。"""
    # 1) Chroma laws_docs 子切片
    try:
        if RAG.is_ready():
            ids = RAG._laws_collection.get(
                where={"file_id": file_id}, include=[]
            ).get("ids", [])
            if ids:
                RAG._laws_collection.delete(ids=ids)
            print(f"[清理] Chroma laws_docs 删除子切片 {len(ids)} 条")
        else:
            print("[清理] RAG 未就绪，Chroma 无待删数据（或初始化失败，跳过）")
    except Exception as e:
        print(f"[清理] Chroma 删除失败: {e}")

    # 2) Postgres bm25 子关键词行
    try:
        import psycopg

        with psycopg.connect(getattr(legal_ingest._bm25, "postgreSQL_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {legal_ingest._bm25.BM25_TABLE} WHERE file_id = %s",
                    (file_id,),
                )
            conn.commit()
        print("[清理] Postgres bm25 子行已清空")
    except Exception as e:
        print(f"[清理] bm25 删除失败: {e}")

    # 3) Postgres laws 父行
    try:
        n = parent_store.delete_file(file_id)
        print(f"[清理] Postgres laws 删除父行 {n} 条")
    except Exception as e:
        print(f"[清理] laws 删除失败: {e}")


def _run_pipeline(parse, RAG, parent_store, legal_ingest) -> None:
    text = (Path(__file__).parent / "sample_law.txt").read_text(encoding="utf-8")

    # ── 1. 父子切分 ──
    parts = parse.chunk_laws(text, file_id=FILE_ID)
    parents, children = parts["parents"], parts["children"]
    print(f"[1] 切分: 父 {len(parents)} 块 / 子 {len(children)} 块")
    print("    父长:", [len(p["content"]) for p in parents])
    print("    子长(min/max):", min(len(c["content"]) for c in children),
          "/", max(len(c["content"]) for c in children))
    m = children[0]["metadata"]
    print("    子0 metadata keys:", sorted(m.keys()))
    assert all(c["metadata"].get("parent_index") is not None for c in children)
    assert all(c["metadata"].get("parent_heading") for c in children)

    # ── 2. 入库（对齐 legal_ingest 双写 + 父表）──
    if not RAG.is_ready():
        RAG.init()
    assert RAG.is_ready(), "RAG 未就绪（Chroma/模型加载失败）"
    assert RAG.upsert_chunks(children, target="laws"), "Chroma 子写入失败"
    legal_ingest.write_bm25_table(children)
    assert parent_store.upsert_parents(parents), "laws 父表写入失败"
    print(f"[2] 入库完成: Chroma(laws_docs) 子 {len(children)} + bm25 子行 + PG laws 父 {len(parents)}")

    # ── 3. 子检索 → 父返回（向量路）──
    query = "不得过度收集个人信息"
    hits = RAG.retrieve_text(query, top_k=5)
    print(f"[3] 向量子命中 {len(hits)} 条，各子 parent_index:",
          [h["metadata"].get("parent_index") for h in hits])
    parents_out = RAG.expand_to_parents(hits, limit=4)
    print("    父返回块数:", len(parents_out))
    for p in parents_out:
        ok = query in p["content"]
        print(f"    - parent_id={p.get('chunk_id')} 长{len(p['content'])} 含查询词={ok}")
    assert any(query in p["content"] for p in parents_out), "父返回未包含查询词！"

    # ── 4. 关键词(BM25)子检索也带父指向 ──
    assert legal_ingest._bm25.init(), "bm25 索引构建失败"
    bm = legal_ingest._bm25.search("撤回同意", top_k=5)
    print(f"[4] BM25 子命中 {len(bm)} 条，parent_index:",
          [r.get("parent_index") for r in bm])
    assert bm and all(r.get("parent_index") is not None for r in bm)
    parents_bm = RAG.expand_to_parents(
        [{"content": r["content"], "metadata": {"file_id": r["file_id"],
                                                 "parent_index": r["parent_index"]}}
         for r in bm], limit=4)
    print("    BM25 展开父返回:", [len(p["content"]) for p in parents_bm])
    assert any("撤回同意" in p["content"] for p in parents_bm)

    print("\nPASS: 切分→入库→子检索→父返回 流程可用")


def main() -> None:
    parse = _load("agents.utils.parse", "parse.py")
    RAG = _load("agents.utils.RAG", "RAG.py")
    parent_store = _load("agents.utils.law_parent_store", "law_parent_store.py")
    legal_ingest = _load("agents.utils.legal_ingest", "legal_ingest.py")  # 复用 write_bm25_table / _bm25

    try:
        _run_pipeline(parse, RAG, parent_store, legal_ingest)
    finally:
        # 无论成功或失败都清掉本用例数据，保证可反复重跑
        print("\n[清理] 删除 sample_law_001 测试数据...")
        _cleanup_store(RAG, parent_store, legal_ingest, FILE_ID)


if __name__ == "__main__":
    main()
