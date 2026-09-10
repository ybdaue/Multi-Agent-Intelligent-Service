"""Postgres 版 LangGraph 长期记忆 store，落库到 my-app 的 agent_store 表。

每个实例绑定一个 agent 名（构造时传入）。行级定位：
  - userId   约定取 namespace 的最后一个元素（当前 legal 用 ("memory", user_id)）
  - agentName 构造时绑定
  - key      把整个 namespace + key 拼成完整路径存进 key 列，
            不同 namespace 类别（如 memory / thread 摘要）互不串。

用法（替换 compile(store=...) 里的 InMemoryStore）：

    from agents.utils.agent_store import create_agent_store
    store = create_agent_store("legal_agent")

说明：
  - BaseStore 的 get/put/search 都经 batch/abatch 分发，仅需实现这二者。
  - 异步走 api.db.pg_pool（由 server lifespan 打开）；同步路径（兼容当前同步
    memory 节点）用本机短连接兜底，同一 DSN。
  - value 必须是 JSON 可序列化 dict；pydantic 对象请先 model_dump()。
  - 本实现支持 GetOp/PutOp/SearchOp；ListNamespacesOp 未实现（调用会报错）。
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable
from typing import Any

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
)

logger = logging.getLogger(__name__)


def create_agent_store(agent_name: str) -> "PostgresStore":
    """创建绑定指定 agent 名的 Postgres 长期记忆 store。"""
    return PostgresStore(agent_name)


def _user_from_namespace(namespace: tuple[str, ...]) -> str:
    if not namespace:
        raise ValueError("namespace 不能为空：无法定位 userId（约定 namespace 末位为 userId）")
    return str(namespace[-1])


def _fq_key(namespace: tuple[str, ...], key: str) -> str:
    return "/".join((*namespace, str(key)))


def _namespace_from_fq(fq: str) -> tuple[str, ...]:
    parts = fq.split("/")
    return tuple(parts[:-1])  # 末段是 key


class PostgresStore(BaseStore):
    """Postgres 版 BaseStore。namespace 末位 = userId，全路径存 key 列。"""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name

    # ---------- async 主路径 ----------
    async def abatch(self, ops: Iterable) -> list[Result]:
        from api.utils.db import pg_pool

        ops = list(ops)
        results: list[Result] = [None] * len(ops)
        async with pg_pool.connection() as conn:
            for i, op in enumerate(ops):
                if isinstance(op, GetOp):
                    results[i] = await self._aget(conn, op)
                elif isinstance(op, PutOp):
                    await self._aput(conn, op)
                    results[i] = None
                elif isinstance(op, SearchOp):
                    results[i] = await self._asearch(conn, op)
                elif isinstance(op, ListNamespacesOp):
                    raise NotImplementedError(
                        f"{self.__class__.__name__} 未实现 ListNamespacesOp"
                    )
                else:
                    raise TypeError(f"不支持的 store 操作: {type(op).__name__}")
            await conn.commit()
        return results

    async def _aget(self, conn, op: GetOp) -> Item | None:
        user = _user_from_namespace(op.namespace)
        fq = _fq_key(op.namespace, op.key)
        row = (
            await conn.execute(
                'SELECT key, value, "createdAt", "updatedAt" FROM agent_store '
                'WHERE "userId" = %s AND "agentName" = %s AND key = %s',
                [user, self.agent_name, fq],
            )
        ).fetchone()
        return self._row_to_item(row, op.namespace, op.key) if row else None

    async def _aput(self, conn, op: PutOp) -> None:
        user = _user_from_namespace(op.namespace)
        fq = _fq_key(op.namespace, op.key)
        if op.value is None:
            await conn.execute(
                'DELETE FROM agent_store WHERE "userId" = %s AND "agentName" = %s AND key = %s',
                [user, self.agent_name, fq],
            )
            return
        try:
            value_json = json.dumps(op.value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"agent_store 的 value 必须是 JSON 可序列化 dict（got {type(op.value).__name__}），"
                "pydantic 对象请先 model_dump()"
            ) from exc
        await conn.execute(
            'INSERT INTO agent_store (id, "userId", "agentName", key, value, "createdAt", "updatedAt") '
            "VALUES (%s, %s, %s, %s, %s::jsonb, now(), now()) "
            'ON CONFLICT ("userId", "agentName", key) '
            "DO UPDATE SET value = EXCLUDED.value, \"updatedAt\" = now()",
            [uuid.uuid4().hex, user, self.agent_name, fq, value_json],
        )

    async def _asearch(self, conn, op: SearchOp) -> list[SearchItem]:
        prefix = "/".join(op.namespace_prefix) + ("/" if op.namespace_prefix else "")
        like = prefix + "%"
        rows = (
            await conn.execute(
                'SELECT key, value, "createdAt", "updatedAt" FROM agent_store '
                'WHERE "agentName" = %s AND key LIKE %s ORDER BY key',
                [self.agent_name, like],
            )
        ).fetchall()
        items: list[SearchItem] = []
        for row in rows:
            value = row[1]
            if op.filter and not all(
                _value_at_path(value, k) == v for k, v in op.filter.items()
            ):
                continue
            namespace = _namespace_from_fq(row[0])
            items.append(
                SearchItem(
                    namespace=namespace,
                    key=row[0].split("/")[-1],
                    value=value,
                    created_at=row[2],
                    updated_at=row[3],
                )
            )
        return items[op.offset : op.offset + op.limit]

    # ---------- sync 兼容路径 ----------
    def batch(self, ops: Iterable) -> list[Result]:
        import psycopg

        from api.utils.db import postgreSQL_URL

        ops = list(ops)
        results: list[Result] = [None] * len(ops)
        with psycopg.connect(postgreSQL_URL) as conn:
            for i, op in enumerate(ops):
                if isinstance(op, GetOp):
                    results[i] = self._sync_aget(conn, op)
                elif isinstance(op, PutOp):
                    self._sync_aput(conn, op)
                    results[i] = None
                elif isinstance(op, SearchOp):
                    results[i] = self._sync_asearch(conn, op)
                elif isinstance(op, ListNamespacesOp):
                    raise NotImplementedError(
                        f"{self.__class__.__name__} 未实现 ListNamespacesOp"
                    )
                else:
                    raise TypeError(f"不支持的 store 操作: {type(op).__name__}")
            conn.commit()
        return results

    def _sync_aget(self, conn, op: GetOp) -> Item | None:
        user = _user_from_namespace(op.namespace)
        fq = _fq_key(op.namespace, op.key)
        row = conn.execute(
            'SELECT key, value, "createdAt", "updatedAt" FROM agent_store '
            'WHERE "userId" = %s AND "agentName" = %s AND key = %s',
            [user, self.agent_name, fq],
        ).fetchone()
        return self._row_to_item(row, op.namespace, op.key) if row else None

    def _sync_aput(self, conn, op: PutOp) -> None:
        user = _user_from_namespace(op.namespace)
        fq = _fq_key(op.namespace, op.key)
        if op.value is None:
            conn.execute(
                'DELETE FROM agent_store WHERE "userId" = %s AND "agentName" = %s AND key = %s',
                [user, self.agent_name, fq],
            )
            return
        try:
            value_json = json.dumps(op.value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"agent_store 的 value 必须是 JSON 可序列化 dict（got {type(op.value).__name__}），"
                "pydantic 对象请先 model_dump()"
            ) from exc
        conn.execute(
            'INSERT INTO agent_store (id, "userId", "agentName", key, value, "createdAt", "updatedAt") '
            "VALUES (%s, %s, %s, %s, %s::jsonb, now(), now()) "
            'ON CONFLICT ("userId", "agentName", key) '
            "DO UPDATE SET value = EXCLUDED.value, \"updatedAt\" = now()",
            [uuid.uuid4().hex, user, self.agent_name, fq, value_json],
        )

    def _sync_asearch(self, conn, op: SearchOp) -> list[SearchItem]:
        prefix = "/".join(op.namespace_prefix) + ("/" if op.namespace_prefix else "")
        rows = conn.execute(
            'SELECT key, value, "createdAt", "updatedAt" FROM agent_store '
            'WHERE "agentName" = %s AND key LIKE %s ORDER BY key',
            [self.agent_name, prefix + "%"],
        ).fetchall()
        items: list[SearchItem] = []
        for row in rows:
            value = row[1]
            if op.filter and not all(
                _value_at_path(value, k) == v for k, v in op.filter.items()
            ):
                continue
            items.append(
                SearchItem(
                    namespace=_namespace_from_fq(row[0]),
                    key=row[0].split("/")[-1],
                    value=value,
                    created_at=row[2],
                    updated_at=row[3],
                )
            )
        return items[op.offset : op.offset + op.limit]

    @staticmethod
    def _row_to_item(row, namespace, key) -> Item:
        return Item(
            namespace=namespace,
            key=key,
            value=row[1],
            created_at=row[2],
            updated_at=row[3],
        )


def _value_at_path(data: dict, path: str) -> Any:
    """支持简单 a.b 与 a[0]/a[*] 取值；失败返回一个永不相等的哨兵。"""
    cur: Any = data
    for part in path.split("."):
        if part.endswith("]"):
            head, _, tail = part.partition("[")
            if not isinstance(cur, dict) or head not in cur:
                return _MISSING
            cur = cur[head]
            idx = tail[:-1]
            if idx == "*":
                return _MISSING  # 通配简化：不参与过滤
            try:
                i = int(idx)
            except ValueError:
                return _MISSING
            if not isinstance(cur, list) or not -len(cur) <= i < len(cur):
                return _MISSING
            cur = cur[i]
        else:
            if not isinstance(cur, dict) or part not in cur:
                return _MISSING
            cur = cur[part]
    return cur


_MISSING = object()
