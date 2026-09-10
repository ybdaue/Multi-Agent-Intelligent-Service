"""法律库父模块存取 — Postgres laws 表。

父模块是法条检索命中子模块后"返回给 LLM 的整段父文本"。子模块在 Chroma(laws_docs)
与 bm25 表；父模块单独落 PG laws 表（parent_id = {file_id}_P{parent_index}）。

本模块为 standalone（不 import agents 包），legal_ingest 用路径加载、RAG 用惰性加载，
避免触发 agents/__init__.py 的急切导入。
"""

import os
from pathlib import Path
from typing import Any, Optional

import psycopg
from dotenv import load_dotenv

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

postgreSQL_URL = os.getenv("postgreSQL_URL")
if not postgreSQL_URL:
    raise RuntimeError("缺少 postgreSQL_URL，请在 agents-project/.env.development 中配置")

LAWS_TABLE = "laws"


def upsert_parents(parents: list[dict], conn=None) -> bool:
    """把父模块批量 upsert 进 laws 表（按 parent_id 覆盖），失败返回 False。

    conn：批量导入时复用同一事务连接（由调用方 commit），传 None 则自开自提交。
    """
    if not parents:
        return True
    import uuid

    def _exec(cur) -> None:
        for p in parents:
            cur.execute(
                f'''
                INSERT INTO {LAWS_TABLE}
                    (id, parent_id, file_id, parent_index, heading, content)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (parent_id) DO UPDATE SET
                    file_id = EXCLUDED.file_id,
                    parent_index = EXCLUDED.parent_index,
                    heading = EXCLUDED.heading,
                    content = EXCLUDED.content
                ''',
                (
                    str(uuid.uuid4()),
                    p["parent_id"],
                    p["file_id"],
                    p["parent_index"],
                    p.get("heading"),
                    p["content"],
                ),
            )

    try:
        if conn is not None:
            with conn.cursor() as cur:
                _exec(cur)
            return True
        with psycopg.connect(postgreSQL_URL) as own:
            with own.cursor() as cur:
                _exec(cur)
            own.commit()
        return True
    except Exception as e:
        print(f"upsert_parents 失败: {e}")
        return False


def get_parents(parent_ids: list[str]) -> list[dict]:
    """按 parent_id 列表取回父模块（保持传入顺序、自动去重）。返回空列表表示未就绪/无数据。"""
    parent_ids = [str(x) for x in parent_ids if x]
    if not parent_ids:
        return []

    # psycopg 不支持可直接传参的 IN 列表，这里固定长度生成占位符（批次可控）
    placeholders = ",".join(["%s"] * len(parent_ids))
    try:
        with psycopg.connect(postgreSQL_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT parent_id, file_id, parent_index, heading, content '
                    f'FROM {LAWS_TABLE} WHERE parent_id IN ({placeholders})',
                    parent_ids,
                )
                rows = cur.fetchall()
    except Exception as e:
        print(f"get_parents 失败: {e}")
        return []

    by_id = {
        r[0]: {
            "parent_id": r[0],
            "file_id": r[1],
            "parent_index": r[2],
            "heading": r[3],
            "content": r[4],
        }
        for r in rows
    }
    # 保持传入顺序；未命中（该父不存在）直接跳过
    return [by_id[pid] for pid in parent_ids if pid in by_id]


def delete_file(file_id: str) -> int:
    """删除某个 file_id 的全部父模块行，返回删除条数（重导前清理用）。"""
    try:
        with psycopg.connect(postgreSQL_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(f'DELETE FROM {LAWS_TABLE} WHERE file_id = %s', (file_id,))
                n = cur.rowcount
                conn.commit()
        return n
    except Exception as e:
        print(f"delete_file({file_id}) 失败: {e}")
        return 0


def is_ready() -> bool:
    """表是否存在（弱检查），供调试/降级判断。"""
    try:
        with psycopg.connect(postgreSQL_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT to_regclass(%s)", (LAWS_TABLE,)
                )
                return cur.fetchone()[0] is not None
    except Exception:
        return False
