"""BM25 关键词检索引擎 — 基于 Postgres bm25 表建索引。

供 retrieve_law 多路召回使用：从 Postgres `bm25` 表读全部法条全文，
用 rank_bm25 构建 BM25Okapi 内存索引并缓存。服务重启后首次查询懒加载。

所有异常内部消化，未就绪时 search() 返回空列表，检索侧自动只用向量路。
"""

import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

import psycopg
from dotenv import load_dotenv
from psycopg import sql

# 本模块会被独立脚本按路径加载（不经 api.utils.config），故自行兜底加载 env
if not os.getenv("postgreSQL_URL"):
    _root = Path(__file__).resolve().parents[2]
    _env_names = [".env.development"]
    if os.getenv("APP_ENV", "").strip().lower() in ("production", "prod"):
        _env_names.insert(0, ".env.production")
    for _name in _env_names:
        if (_root / _name).exists():
            load_dotenv(_root / _name)
            break

# Postgres 连接（与 parse.py / memory.py 相同的同步 psycopg 姿势）
postgreSQL_URL = os.getenv("postgreSQL_URL")
if not postgreSQL_URL:
    raise RuntimeError("缺少 postgreSQL_URL，请在 agents-project/.env.development 中配置")

BM25_TABLE = "bm25"

# jieba 未安装时降级为单字切分，避免 import 拖垮整条检索链（bm25 设计上允许降级）
try:
    import jieba
except Exception:  # pragma: no cover - 依赖缺失时的降级路径
    jieba = None

# 中文切分：先按分隔符切开；纯中文段交给 jieba，拉丁/数字串整词保留
_TOKEN_RE = re.compile(r"[^一-鿿0-9A-Za-z]+")


def _tokenize(text: str) -> list[str]:
    """把文本切成词条列表。中文段用 jieba 切词（缺失时降级逐字），拉丁/数字串成整词。"""
    text = text.lower()  # 拉丁字母归一，避免大小写差异漏词
    tokens = []
    # 先按分隔符切开，保留中英文混排片段
    for seg in _TOKEN_RE.split(text):
        if not seg:
            continue
        if re.fullmatch(r"[一-鿿]+", seg):
            if jieba is not None:
                tokens.extend(jieba.lcut(seg))  # 纯中文整段交给 jieba
            else:
                tokens.extend(list(seg))  # 降级：逐字成 token
        else:
            tokens.append(seg)  # 含拉丁/数字的整段作一个 token
    return tokens


# 模块级缓存：索引与对应文档行（进程内共享，_ready 后不再连库）
_index: Optional[Any] = None
_docs: list[dict[str, Any]] = []
_ready: bool = False
# 串行化冷启动构建：并发首查时只允许一个线程读库建索引
_init_lock = threading.Lock()


def is_ready() -> bool:
    """BM25 索引是否已构建（表非空 + 索引可检索）。"""
    return _ready and _index is not None


def init() -> bool:
    """按需从 bm25 表读取法条全文构建内存索引，进程内只构建一次。

    并发安全：_init_lock 串行化构建 + double-check，避免冷启动并发首查时
    多线程重复全表读；已就绪时直接返回 True。失败不置 ready，下次可重试。
    """
    global _index, _docs, _ready

    if _ready and _index is not None:  # 快速路径：避免每次 search 都抢锁
        return True

    with _init_lock:
        if _ready and _index is not None:  # 等锁期间可能已被其他线程构建完成
            return True

        try:
            with psycopg.connect(postgreSQL_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL(
                            'SELECT chunk_id, content, heading, file_id, chunk_index, parent_index '
                            'FROM {}'
                        ).format(sql.Identifier(BM25_TABLE))
                    )
                    rows = cur.fetchall()
        except Exception as e:
            print(f"bm25 索引加载失败（可重试）: {e}")
            _ready = False
            return False

        if not rows:
            print("bm25 表为空，跳过索引构建")
            _index = None
            _ready = False
            return False

        from rank_bm25 import BM25Okapi

        docs = [
            {"chunk_id": r[0], "content": r[1], "heading": r[2],
             "file_id": r[3], "chunk_index": r[4], "parent_index": r[5]}
            for r in rows
        ]
        _index = BM25Okapi([_tokenize(d["content"]) for d in docs])
        _docs = docs
        _ready = True
        print(f"BM25 索引构建完成，共 {len(docs)} 条法条")
        return True


def search(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """BM25 检索：返回已排序的命中列表，未就绪返回空列表。"""
    if not _ready or _index is None:
        init()
        if not _ready or _index is None:
            return []

    if not query or not query.strip():
        return []

    tokens = _tokenize(query.strip())
    if not tokens:
        return []

    try:
        scores = _index.get_scores(tokens)
    except Exception:
        return []

    # 按得分取 top_k（仅保留得分 > 0 的命中）
    ranked = sorted(
        ((i, s) for i, s in enumerate(scores) if s > 0),
        key=lambda x: x[1],
        reverse=True,
    )[:top_k]

    return [
        {**_docs[i], "bm25_score": score}
        for i, score in ranked
    ]
