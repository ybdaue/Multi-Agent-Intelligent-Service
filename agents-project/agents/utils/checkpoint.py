"""Postgres 版 LangGraph checkpoint saver，落库到 my-app 的 checkpoint 表。

每个实例绑定一个 agent 名（构造时传入）。行级定位三要素：
  - userId   从 config["configurable"]["userId"] 取（缺省 "0"）
  - agentName 构造时绑定
  - threadId  从 config["configurable"]["thread_id"] 取
每次 agent 推进产出的 checkpoint 作为一行“追加式快照”写入
(userId, agentName, threadId, checkpointId) 唯一，历史可回溯。
每个 (userId, agentName, threadId) 对话只保留最近 MAX_SNAPSHOTS 个快照，
写入超出上限时同事务内删除最旧的（见 aput/put 末尾的裁剪）。

用法（替换 compile(checkpointer=...) 里的 BoundedMemorySaver）：

    from agents.utils.checkpoint import create_checkpoint
    checkpointer = create_checkpoint("legal_agent")

说明：
  - 写入需 userId 进入 config：invoke 时 {"configurable": {"thread_id":..., "userId":...}}
  - 异步方法走 api.db.pg_pool（由 server lifespan 打开）；同步方法为兼容 sync
    invoke 用本机短连接兜底（同一 DSN）。首选异步调用。
  - 序列化复用 langgraph 默认 JsonPlusSerializer（msgpack），以 base64 塞进 jsonb 列，
    保证 messages 等对象读回后仍是 BaseMessage 类型。
  - 该实现暂不感知 checkpoint_ns / DeltaChannel，超时/中断语义以最新快照为主。
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

logger = logging.getLogger(__name__)

# 单个对话 (userId, agentName, threadId) 最多保留的快照数，超出删最旧
MAX_SNAPSHOTS = 20

_PRUNE_SQL = (
    'DELETE FROM checkpoint '
    'WHERE "userId" = %s AND "agentName" = %s AND "threadId" = %s '
    'AND "checkpointId" NOT IN ('
    '  SELECT "checkpointId" FROM checkpoint '
    '  WHERE "userId" = %s AND "agentName" = %s AND "threadId" = %s '
    '  ORDER BY "checkpointId" DESC LIMIT %s'
    ')'
)


def _anon_user(config: RunnableConfig) -> str:
    cfg = config.get("configurable", {})
    uid = cfg.get("userId")
    if uid is None:
        uid = cfg.get("user_id")
    return str(uid) if uid is not None else "0"


def _thread_id(config: RunnableConfig) -> str:
    return config["configurable"]["thread_id"]


def create_checkpoint(agent_name: str) -> "PostgresCheckpointSaver":
    """创建绑定指定 agent 名的 Postgres checkpoint saver。"""
    return PostgresCheckpointSaver(agent_name)


class PostgresCheckpointSaver(BaseCheckpointSaver):
    def __init__(self, agent_name: str, *, serde=None):
        super().__init__(serde=serde)
        self.agent_name = agent_name

    # ---- 序列化辅助：msgpack 二进制 -> base64，塞进 jsonb ----
    def _pack(self, obj: Any) -> dict:
        typ, data = self.serde.dumps_typed(obj)
        return {"serde": typ, "payload": base64.b64encode(data).decode("ascii")}

    def _unpack(self, blob: dict) -> Any:
        typ = blob["serde"]
        data = base64.b64decode(blob["payload"].encode("ascii"))
        return self.serde.loads_typed((typ, data))

    def _meta_blob(self, metadata: CheckpointMetadata, pending: list[dict]) -> dict:
        return self._pack({"metadata": dict(metadata or {}), "pending": pending})

    @staticmethod
    def _ret_config(thread_id: str, checkpoint_id: str) -> RunnableConfig:
        # 仅回填定位键；userId 等运行时键始终由调用方 config 携带
        return {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}

    # ---- async: 主路径，走 api.db.pg_pool ----
    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        from api.utils.db import pg_pool

        uid = _anon_user(config)
        tid = _thread_id(config)
        cp_id = config["configurable"].get("checkpoint_id")

        params: list = [uid, self.agent_name, tid]
        if cp_id:
            params.append(cp_id)

        async with pg_pool.connection() as conn:
            cur = await conn.execute(
                'SELECT "checkpointId", state, metadata FROM checkpoint '
                'WHERE "userId" = %s AND "agentName" = %s AND "threadId" = %s'
                + (" AND \"checkpointId\" = %s" if cp_id else "")
                + ' ORDER BY "checkpointId" DESC LIMIT 1',
                params,
            )
            row = await cur.fetchone()

        if row is None:
            return None
        cp_id = row[0]
        checkpoint = self._unpack(row[1])
        payload = self._unpack(row[2])
        metadata = payload.get("metadata") or {}
        pending_writes = None
        if payload.get("pending"):
            pending_writes = [
                (e["task_id"], e["channel"], self._unpack(e["value"]))
                for e in payload["pending"]
            ]
        return CheckpointTuple(
            config=self._ret_config(tid, cp_id),
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=None,
            pending_writes=pending_writes,
        )

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions,
    ) -> RunnableConfig:
        from api.utils.db import pg_pool

        uid = _anon_user(config)
        tid = _thread_id(config)
        cp_id = checkpoint["id"]
        state_blob = json.dumps(self._pack(checkpoint), ensure_ascii=False)
        meta_blob = json.dumps(self._meta_blob(metadata, []), ensure_ascii=False)

        async with pg_pool.connection() as conn:
            await conn.execute(
                'INSERT INTO checkpoint (id, "userId", "agentName", "threadId", '
                '"checkpointId", state, metadata, "createdAt", "updatedAt") '
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, now(), now()) "
                'ON CONFLICT ("userId", "agentName", "threadId", "checkpointId") '
                "DO UPDATE SET state = EXCLUDED.state, metadata = EXCLUDED.metadata, "
                '"updatedAt" = now()',
                [uuid.uuid4().hex, uid, self.agent_name, tid, cp_id, state_blob, meta_blob],
            )
            await conn.execute(
                _PRUNE_SQL,
                [uid, self.agent_name, tid, uid, self.agent_name, tid, MAX_SNAPSHOTS],
            )
            await conn.commit()
        return self._ret_config(tid, cp_id)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        from api.utils.db import pg_pool

        uid = _anon_user(config)
        tid = _thread_id(config)
        cp_id = config["configurable"]["checkpoint_id"]

        async with pg_pool.connection() as conn:
            cur = await conn.execute(
                'SELECT metadata FROM checkpoint WHERE "userId" = %s AND "agentName" = %s AND "threadId" = %s AND "checkpointId" = %s',
                [uid, self.agent_name, tid, cp_id],
            )
            row = await cur.fetchone()
            if row is None:
                return  # checkpoint 行尚未落库，忽略（不打断主流程）
            payload = self._unpack(row[0])
            pending = payload.setdefault("pending", [])
            existing = {(e["task_id"], e["channel"]) for e in pending}
            for channel, value in writes:
                if (task_id, channel) in existing:
                    continue
                pending.append(
                    {
                        "task_id": task_id,
                        "channel": channel,
                        "task_path": task_path,
                        "value": self._pack(value),
                    }
                )
                existing.add((task_id, channel))
            new_blob = json.dumps(self._meta_blob(payload.get("metadata") or {}, pending), ensure_ascii=False)
            await conn.execute(
                'UPDATE checkpoint SET metadata = %s::jsonb, "updatedAt" = now() '
                'WHERE "userId" = %s AND "agentName" = %s AND "threadId" = %s AND "checkpointId" = %s',
                [new_blob, uid, self.agent_name, tid, cp_id],
            )
            await conn.commit()

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        from api.utils.db import pg_pool

        if config is None:
            raise NotImplementedError("PostgresCheckpointSaver 不支持全库 list，请传入带 userId/thread_id 的 config")
        uid = _anon_user(config)
        tid = _thread_id(config)

        async with pg_pool.connection() as conn:
            cur = await conn.execute(
                'SELECT "checkpointId", state, metadata FROM checkpoint '
                'WHERE "userId" = %s AND "agentName" = %s AND "threadId" = %s '
                'ORDER BY "checkpointId" DESC',
                [uid, self.agent_name, tid],
            )
            rows = await cur.fetchall()

        before_id = None
        if before:
            before_id = before["configurable"].get("checkpoint_id")
        for row in rows:
            cp_id = row[0]
            if before_id and cp_id >= before_id:
                continue
            if limit is not None:
                if limit <= 0:
                    break
                limit -= 1
            payload = self._unpack(row[2])
            metadata = payload.get("metadata") or {}
            if filter and not all(
                metadata.get(k) == v for k, v in filter.items()
            ):
                continue
            checkpoint = self._unpack(row[1])
            yield CheckpointTuple(
                config=self._ret_config(tid, cp_id),
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=None,
            )

    async def adelete_thread(self, thread_id: str) -> None:
        from api.utils.db import pg_pool

        async with pg_pool.connection() as conn:
            await conn.execute(
                'DELETE FROM checkpoint WHERE "agentName" = %s AND "threadId" = %s',
                [self.agent_name, thread_id],
            )
            await conn.commit()

    # ---- sync: 兼容同步 invoke，用本机短连接 ----
    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        rows = self._sync_query(config)
        if not rows:
            return None
        row = rows[0]
        uid = _anon_user(config)
        tid = _thread_id(config)
        cp_id = row[0]
        checkpoint = self._unpack(row[1])
        payload = self._unpack(row[2])
        metadata = payload.get("metadata") or {}
        pending_writes = None
        if payload.get("pending"):
            pending_writes = [
                (e["task_id"], e["channel"], self._unpack(e["value"]))
                for e in payload["pending"]
            ]
        return CheckpointTuple(
            config=self._ret_config(tid, cp_id),
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=None,
            pending_writes=pending_writes,
        )

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions,
    ) -> RunnableConfig:
        import psycopg

        from api.utils.db import postgreSQL_URL

        uid = _anon_user(config)
        tid = _thread_id(config)
        cp_id = checkpoint["id"]
        state_blob = json.dumps(self._pack(checkpoint), ensure_ascii=False)
        meta_blob = json.dumps(self._meta_blob(metadata, []), ensure_ascii=False)
        with psycopg.connect(postgreSQL_URL) as conn:
            conn.execute(
                'INSERT INTO checkpoint (id, "userId", "agentName", "threadId", '
                '"checkpointId", state, metadata, "createdAt", "updatedAt") '
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, now(), now()) "
                'ON CONFLICT ("userId", "agentName", "threadId", "checkpointId") '
                "DO UPDATE SET state = EXCLUDED.state, metadata = EXCLUDED.metadata, "
                '"updatedAt" = now()',
                [uuid.uuid4().hex, uid, self.agent_name, tid, cp_id, state_blob, meta_blob],
            )
            conn.execute(
                _PRUNE_SQL,
                [uid, self.agent_name, tid, uid, self.agent_name, tid, MAX_SNAPSHOTS],
            )
            conn.commit()
        return self._ret_config(tid, cp_id)

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        import psycopg

        from api.utils.db import postgreSQL_URL

        uid = _anon_user(config)
        tid = _thread_id(config)
        cp_id = config["configurable"]["checkpoint_id"]
        with psycopg.connect(postgreSQL_URL) as conn:
            row = conn.execute(
                'SELECT metadata FROM checkpoint WHERE "userId" = %s AND "agentName" = %s AND "threadId" = %s AND "checkpointId" = %s',
                [uid, self.agent_name, tid, cp_id],
            ).fetchone()
            if row is None:
                return
            payload = self._unpack(row[0])
            pending = payload.setdefault("pending", [])
            existing = {(e["task_id"], e["channel"]) for e in pending}
            for channel, value in writes:
                if (task_id, channel) in existing:
                    continue
                pending.append(
                    {
                        "task_id": task_id,
                        "channel": channel,
                        "task_path": task_path,
                        "value": self._pack(value),
                    }
                )
                existing.add((task_id, channel))
            new_blob = json.dumps(self._meta_blob(payload.get("metadata") or {}, pending), ensure_ascii=False)
            conn.execute(
                'UPDATE checkpoint SET metadata = %s::jsonb, "updatedAt" = now() '
                'WHERE "userId" = %s AND "agentName" = %s AND "threadId" = %s AND "checkpointId" = %s',
                [new_blob, uid, self.agent_name, tid, cp_id],
            )
            conn.commit()

    def _sync_query(self, config: RunnableConfig) -> list[tuple]:
        import psycopg

        from api.utils.db import postgreSQL_URL

        uid = _anon_user(config)
        tid = _thread_id(config)
        cp_id = config["configurable"].get("checkpoint_id")
        params: list = [uid, self.agent_name, tid]
        if cp_id:
            params.append(cp_id)
        with psycopg.connect(postgreSQL_URL) as conn:
            cur = conn.execute(
                'SELECT "checkpointId", state, metadata FROM checkpoint '
                'WHERE "userId" = %s AND "agentName" = %s AND "threadId" = %s'
                + (' AND "checkpointId" = %s' if cp_id else "")
                + ' ORDER BY "checkpointId" DESC LIMIT 1',
                params,
            )
            return cur.fetchall()
