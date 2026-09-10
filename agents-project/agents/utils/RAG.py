import importlib.util
import os
import sys
import time

import chromadb
import torch
from chromadb.config import Settings
from pathlib import Path
from typing import Any, Dict, List, Optional
from sentence_transformers import SentenceTransformer

# 用户上传切片在向量库中的存活时长（3 天），超时后由 delete_expired_chunks 清理
FILE_TTL_SECONDS = 3 * 24 * 60 * 60

# 本地 embedding 模型目录（离线加载，不再联网下载）
# 本文件在 agents/utils/ 下，向上三级才是 agents-project/
MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "models" / "bge-large-zh-v1.5"

# 有 NVIDIA GPU 且 torch 为 CUDA 版则用显卡，否则降级 CPU（不报错）
_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

_client: Optional[chromadb.HttpClient] = None
_collection = None
_laws_collection = None
_embedder: Optional[SentenceTransformer] = None
_model_ready: bool = False
_chroma_ready: bool = False

# 初始化 Chroma 连接和 embedding 模型
def init() -> None:
    global _client, _collection, _laws_collection, _embedder, _model_ready, _chroma_ready

    # 模型只加载一次，失败也不重试
    if not _model_ready:
        try:
            # 加载 embedding 模型（本地跑，不在 Docker 里）；有卡上 cuda，无卡降级 cpu
            _embedder = SentenceTransformer(str(MODEL_DIR), device=_DEVICE)
            _model_ready = True
            print(f"Embedding 模型加载完成（device={_DEVICE}）")
        except Exception as e:
            print(f"Embedding 模型加载失败（不会重试）: {e}")
            _chroma_ready = False
            return

    # Chroma 连接可反复重试
    try:
        # 连 Docker 里的 Chroma
        _client = chromadb.HttpClient(
            host="localhost",   # Docker 在宿主机跑：localhost
            port=8000,
            settings=Settings(anonymized_telemetry=False),
        )
        # 心跳测试
        print("Chroma 版本:", _client.heartbeat())

        # 用户上传的文件表
        _collection = _client.get_or_create_collection(
            name="legal_docs",
            metadata={"hnsw:space": "cosine"},
        )
        # 系统配置的法律法规表
        _laws_collection = _client.get_or_create_collection(
            name="laws_docs",
            metadata={"hnsw:space": "cosine"},
        )
        print("Collection 数量:", _client.list_collections())

        _chroma_ready = True
        print("RAG 初始化完成")
    except Exception as e:
        print(f"Chroma 连接失败（将重试）: {e}")
        _chroma_ready = False


def is_ready() -> bool:
    return _model_ready and _chroma_ready and _laws_collection is not None

# 将分块文本写入 Chroma 向量库
def upsert_chunks(chunks: List[Dict[str, Any]], target: str = "docs") -> Optional[bool]:
    """
    target="docs" → 写入 legal_docs（用户上传文件）
    target="laws" → 写入 laws_docs（系统法律法规） 
    """
    if not is_ready():
        init()
        if not is_ready():
            return False

    if not chunks:
        return

    col = _laws_collection if target == "laws" else _collection

    try:
        documents = [c["content"] for c in chunks]
        # 用户上传切片打上 created_at 时间戳，供 TTL 清扫使用；系统法条表不参与过期
        metadatas = []
        for c in chunks:
            meta = dict(c["metadata"])
            if target != "laws":
                meta["created_at"] = time.time()
            metadatas.append(meta)
        ids = [
            f"{c['metadata']['file_id']}_{c['metadata']['chunk_index']}"
            for c in chunks
        ]
        embeddings = _embedder.encode(documents, normalize_embeddings=True).tolist()
        col.upsert(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )
        return True

    except Exception as e:
        print(f"upsert_chunks 失败: {e}")
        return False

# 把整批文本一次性向量化
def embed_documents(documents: list[str], *, batch_size: int = 128) -> list:
    if not documents:
        return []
    if _embedder is None:
        init()
    if _embedder is None:
        return []
    try:
        return _embedder.encode(documents, batch_size=batch_size, normalize_embeddings=True).tolist()
    except Exception as e:
        print(f"embed_documents 失败: {e}")
        return []

# 用调用方已算好的 embeddings 直接入库（不再二次 encode）
def upsert_preembedded(
    *,
    documents: list[str],
    embeddings: list,
    metadatas: list[dict],
    ids: list[str],
    target: str = "laws",
) -> bool:
    if not is_ready():
        init()
        if not is_ready():
            return False
    if not documents:
        return True

    col = _laws_collection if target == "laws" else _collection
    try:
        col.upsert(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )
        return True
    except Exception as e:
        print(f"upsert_preembedded 失败: {e}")
        return False

# 删除 legal_docs 中 created_at 早于 cutoff 的过期切片，返回删除数量
def delete_expired_chunks(cutoff: float) -> int:
    if not is_ready():
        init()
        if not is_ready():
            return 0

    try:
        result = _collection.get(where={"created_at": {"$lt": cutoff}})
        ids = result.get("ids", []) if result else []
        if ids:
            _collection.delete(ids=ids)
        return len(ids)
    except Exception as e:
        print(f"delete_expired_chunks 失败: {e}")
        return 0

# 返回指定 file_id 的切片数量
def get_chunk_num(file_id: str) -> int:
    if not is_ready():
        init()
        if not is_ready():
            return 0

    try:
        # 只取 id 计数，不拉回 documents/embeddings，避免大文件全量进内存
        result = _collection.get(
            where={"file_id": file_id},
            include=[],
        )
        return len(result.get("ids", [])) if result else 0
    except Exception as e:
        print(f"get_chunk_num 失败: {e}")
        return 0

# 根据 file_id 和分页参数取出对应 chunk，按 chunk_index 排序
def get_chunk(file_id: str, page: int = 1, limit: int = 10) -> list[dict[str, Any]]:
    if not is_ready():
        init()
        if not is_ready():
            return []

    try:
        start = (page - 1) * limit
        # chromadb 要求顶层 where 只能有一个条件、字段运算符只能有一个，多字段须用 $and 包裹
        result = _collection.get(
            where={
                "$and": [
                    {"file_id": file_id},
                    {"chunk_index": {"$gte": start}},
                    {"chunk_index": {"$lt": start + limit}},
                ]
            },
            include=["documents", "metadatas", "embeddings"],
        )
        if result is None or not result.get("documents"):
            return []

        chunks = []
        for i in range(len(result["documents"])):
            chunks.append({
                "content": result["documents"][i],
                "metadata": result["metadatas"][i] if result.get("metadatas") is not None else {},
                "embedding": result["embeddings"][i] if result.get("embeddings") is not None else None,
            })
        # 页内最多 limit 条，排序开销可忽略
        chunks.sort(key=lambda c: c["metadata"].get("chunk_index", 0))
        return chunks

    except Exception as e:
        print(f"get_chunk 失败: {e}")
        return []

# 对每个 chunk 在法律表中检索相似法条（top_k=5）
def retrieve_chunk(chunks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if not is_ready():
        init()
        if not is_ready():
            return []

    if not chunks:
        return []

    try:
        embeddings = [c["embedding"] for c in chunks]
        raw = _laws_collection.query(query_embeddings=embeddings, n_results=5)

        return [_format_single(raw, i) for i in range(len(chunks))]

    except Exception as e:
        print(f"retrieve_chunk 失败: {e}")
        return []

# 从批量查询结果中提取单条 query 的结果
def _format_single(raw, idx: int) -> list[dict[str, Any]]:
    docs = raw.get("documents", [[]])[idx]
    metas = raw.get("metadatas", [[]])[idx] if raw.get("metadatas") is not None else [{}] * len(docs)
    dists = raw.get("distances", [[]])[idx] if raw.get("distances") is not None else [None] * len(docs)
    return [
        {"content": docs[i], "metadata": metas[i], "distance": dists[i]}
        for i in range(len(docs))
    ]


_law_parent_mod = None

# 惰性按文件路径加载 law_parent_store，避免走 agents 包导入链
def _load_law_parent_store():
    global _law_parent_mod
    if _law_parent_mod is not None:
        return _law_parent_mod
    mod_name = "agents.utils.law_parent_store"
    path = Path(__file__).resolve().parent / "law_parent_store.py"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    _law_parent_mod = mod
    return mod

# 取子命中所属父 id（{file_id}_P{parent_index}）；无父信息返回 None。
def _child_parent_id(hit: dict) -> str | None:
    meta = hit.get("metadata") or {}
    file_id = hit.get("file_id") if hit.get("file_id") is not None else meta.get("file_id")
    parent_index = hit.get("parent_index") if hit.get("parent_index") is not None else meta.get("parent_index")
    if file_id is None or parent_index is None:
        return None
    return f"{file_id}_P{parent_index}"

# 把"命中的子模块"展开为对应父模块整段，供返回 LLM 使用
def expand_to_parents(child_hits: list[dict], *, limit: int = 6) -> list[dict]:
    if not child_hits:
        return []

    ordered_pids: list[str] = []
    pid_of: dict[str, dict] = {}
    passthrough: list[dict] = []  # 无父信息的子，原样保留

    for hit in child_hits:
        pid = _child_parent_id(hit)
        if pid is None:
            passthrough.append(hit)
            continue
        if pid not in pid_of:
            pid_of[pid] = hit
            ordered_pids.append(pid)

    if not ordered_pids:
        return passthrough[:limit]

    try:
        parents = _load_law_parent_store().get_parents(ordered_pids)
    except Exception as e:
        print(f"expand_to_parents 父表查询失败，退回子命中: {e}")
        return child_hits[:limit]

    parents_by_id = {p["parent_id"]: p for p in parents}

    result: list[dict] = []
    for pid in ordered_pids:
        best = pid_of[pid]
        parent = parents_by_id.get(pid)
        if parent is None:
            # 父行缺失：退回子，保底可用
            result.append(best)
            continue
        result.append({
            "content": parent["content"],
            "metadata": {
                "file_id": parent["file_id"],
                "parent_index": parent["parent_index"],
                "heading": parent["heading"],
            },
            "distance": best.get("distance"),
            "chunk_id": pid,
            "parent_id": pid,
        })
    result.extend(passthrough)
    return result[:limit]

# 对输入文本进行 embedding，在法律表中检索相关法律内容
def retrieve_text(text: str, top_k: int = 5) -> list[dict[str, Any]]:
    if not is_ready():
        init()
        if not is_ready():
            return []

    try:
        query_embedding = _embedder.encode(text, normalize_embeddings=True).tolist()
        results = _laws_collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )
        return _format_results(results)

    except Exception as e:
        print(f"retrieve_text 失败: {e}")
        return []

# 将 Chroma 原生查询结果格式化为统一结构
def _format_results(results) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    if results is None or not results.get("documents"):
        return formatted

    for i in range(len(results["documents"][0])):
        formatted.append({
            "content": results["documents"][0][i],
            "metadata": results["metadatas"][0][i] if results.get("metadatas") is not None else {},
            "distance": results["distances"][0][i] if results.get("distances") is not None else None,
        })

    return formatted
