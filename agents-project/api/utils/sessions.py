"""通用「会话列表 / 会话历史」读取（读 user_session / user_session_history）。

与具体 agent 域解耦：按 (userId, agentName) 取会话列表、按
(userId, agentName, threadId) 取单个会话的对话历史。
调用方负责鉴权并传入真实 userId（来自 request.state.user_id）。

写入方在 agents/legal/memory.py：checkin 节点（请求开始存会话行+本轮提问）
与 update 节点（每轮结束追加问答），定位 key 与读取端一致。
"""
from api.utils.db import pg_pool


async def _fetch(sql: str, params: tuple):
    async with pg_pool.connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchall()


def _session_payload(row: tuple) -> dict:
    id_, agent_name, thread_id, title, created_at, updated_at = row
    return {
        "id": id_,
        "agentName": agent_name,
        "threadId": thread_id,
        "title": title,
        "createdAt": created_at,
        "updatedAt": updated_at,
    }


async def list_sessions(
    user_id: str, agent_name: str = "", page: int = 1, page_size: int = 20
) -> tuple[list[dict], int]:
    """某用户下全部（agent_name 为空）或指定 agent 的会话，按最近更新倒序分页。

    返回 (sessions, total)：sessions 为当前页记录，total 为满足条件的总条数。
    """
    where = '"userId" = %s'
    params: list = [user_id]
    if agent_name:
        where += ' AND "agentName" = %s'
        params.append(agent_name)

    total = (await _fetch(
        f'SELECT count(*) FROM user_session WHERE {where}', tuple(params)
    ))[0][0]

    rows = await _fetch(
        'SELECT id, "agentName", "threadId", title, "createdAt", "updatedAt" '
        f'FROM user_session WHERE {where} '
        'ORDER BY "updatedAt" DESC '
        'LIMIT %s OFFSET %s',
        tuple(params + [page_size, (page - 1) * page_size]),
    )
    return [_session_payload(r) for r in rows], total


async def get_session_history(
    user_id: str, agent_name: str, thread_id: str
) -> dict | None:
    """某用户某 agent 某会话的对话历史；会话不存在时返回 None。"""
    session_rows = await _fetch(
        'SELECT id, "agentName", "threadId", title, "createdAt", "updatedAt" '
        'FROM user_session '
        'WHERE "userId" = %s AND "agentName" = %s AND "threadId" = %s',
        (user_id, agent_name, thread_id),
    )
    if not session_rows:
        return None

    payload = _session_payload(session_rows[0])
    history_rows = await _fetch(
        'SELECT messages FROM user_session_history WHERE "sessionId" = %s',
        (payload["id"],),
    )
    payload["messages"] = history_rows[0][0] if history_rows else []
    return payload
