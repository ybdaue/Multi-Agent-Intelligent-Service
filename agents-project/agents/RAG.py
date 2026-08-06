import time

import chromadb
from chromadb.config import Settings
from pathlib import Path
from typing import Any, Dict, List, Optional
from sentence_transformers import SentenceTransformer

# 用户上传切片在向量库中的存活时长（3 天），超时后由 delete_expired_chunks 清理
FILE_TTL_SECONDS = 3 * 24 * 60 * 60

# 本地 embedding 模型目录（离线加载，不再联网下载）
MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "bge-large-zh-v1.5"

_client: Optional[chromadb.HttpClient] = None
_collection = None
_laws_collection = None
_embedder: Optional[SentenceTransformer] = None
_model_ready: bool = False
_chroma_ready: bool = False


def init() -> None:
    """初始化 Chroma 连接和 embedding 模型。
    所有异常内部消化，不会影响服务启动。调用方可通过 is_ready() 检查状态。
    模型只会加载一次，Chroma 连接失败后可反复重试。
    """
    global _client, _collection, _laws_collection, _embedder, _model_ready, _chroma_ready

    # 模型只加载一次，失败也不重试
    if not _model_ready:
        try:
            # 加载 embedding 模型（本地跑，不在 Docker 里）
            _embedder = SentenceTransformer(str(MODEL_DIR))
            _model_ready = True
            print("Embedding 模型加载完成")
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


def upsert_chunks(chunks: List[Dict[str, Any]], target: str = "docs") -> Optional[bool]:
    """将分块文本写入 Chroma 向量库。

    target="docs" → 写入 legal_docs（用户上传文件）
    target="laws" → 写入 laws_docs（系统法律法规） 

    返回 True 表示写入成功，False 表示写入失败，None 表示没有数据需要写入。
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


def delete_expired_chunks(cutoff: float) -> int:
    """删除 legal_docs 中 created_at 早于 cutoff 的过期切片，返回删除数量。"""
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


def get_chunk_num(file_id: str) -> int:
    """返回指定 file_id 的切片数量。"""
    if not is_ready():
        init()
        if not is_ready():
            return 0

    try:
        result = _collection.get(where={"file_id": file_id})
        if result is None or not result.get("documents"):
            return 0
        return len(result["documents"])
    except Exception as e:
        print(f"get_chunk_num 失败: {e}")
        return 0


def get_chunk(file_id: str, page: int = 1, limit: int = 10) -> list[dict[str, Any]]:
    """根据 file_id 和分页参数取出对应 chunk，按 chunk_index 排序。

    返回对象包含 content、metadata 和已归一化的 embedding，可直接用于检索。
    """
    if not is_ready():
        init()
        if not is_ready():
            return []

    try:
        result = _collection.get(
            where={"file_id": file_id},
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
        chunks.sort(key=lambda c: c["metadata"].get("chunk_index", 0))

        start = (page - 1) * limit
        return chunks[start:start + limit]

    except Exception as e:
        print(f"get_chunk 失败: {e}")
        return []


def retrieve_chunk(chunks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """对每个 chunk 在法律表中检索相似法条（top_k=5），复用已存储的 embedding。
    批量查询减少网络往返，返回二维数组：result[i] 对应 chunks[i] 的 5 个检索结果。
    """
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


def _format_single(raw, idx: int) -> list[dict[str, Any]]:
    """从批量查询结果中提取单条 query 的结果。"""
    docs = raw.get("documents", [[]])[idx]
    metas = raw.get("metadatas", [[]])[idx] if raw.get("metadatas") is not None else [{}] * len(docs)
    dists = raw.get("distances", [[]])[idx] if raw.get("distances") is not None else [None] * len(docs)
    return [
        {"content": docs[i], "metadata": metas[i], "distance": dists[i]}
        for i in range(len(docs))
    ]


def retrieve_text(text: str, top_k: int = 5) -> list[dict[str, Any]]:
    """对输入文本进行 embedding，在法律表中检索相关法律内容。"""
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


def _format_results(results) -> list[dict[str, Any]]:
    """将 Chroma 原生查询结果格式化为统一结构。"""
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
