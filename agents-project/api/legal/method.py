from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from api.utils.db import pg_pool
from api.utils.sessions import delete_session as _delete_session
from api.utils.sessions import get_session_history as _get_session_history
from api.utils.sessions import list_sessions as _list_sessions

router = APIRouter(prefix="/api/legal/method", tags=["法律服务"])


@router.get("/sessions")
async def list_user_sessions(
    request: Request,
    userId: int = Query(..., description="登录用户稳定哈希 ID（与写库所用 key 一致）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
):
    """当前登录用户的法律会话列表，按最近更新倒序分页。

    legal_agent 写库时以调用方传入的稳定哈希 userId 作为隔离 key，
    此处改用显式 userId 过滤，保持读写一致（鉴权仍由全局 auth 中间件保证）。
    """
    sessions, total = await _list_sessions(
        str(userId), "legal_agent", page, page_size
    )
    return {"sessions": sessions, "total": total, "page": page, "page_size": page_size}


@router.get("/sessions/history")
async def get_session_history(
    request: Request,
    userId: int = Query(..., description="登录用户稳定哈希 ID（与写库所用 key 一致）"),
    threadId: str = Query(..., description="会话 ID（threadId）"),
):
    """当前登录用户在 legal_agent 下某个会话的对话历史。"""
    data = await _get_session_history(str(userId), "legal_agent", threadId)
    if data is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return data


@router.delete("/sessions")
async def delete_user_session(
    request: Request,
    userId: int = Query(..., description="登录用户稳定哈希 ID（与写库所用 key 一致）"),
    threadId: str = Query(..., description="会话 ID（threadId）"),
):
    """删除当前登录用户在该 agent 下的一个会话（含对话历史与 LangGraph 快照）。"""
    deleted = await _delete_session(str(userId), "legal_agent", threadId)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"deleted": True, "threadId": threadId}


@router.get("/download/{userId}/{fileId}")
async def download_file(userId: int, fileId: str):
    """下载 agent 生成的文书文件（created_file 表，按 userId 隔离鉴权）。"""
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT "originalName", "mimeType", data FROM created_file '
            'WHERE id = %s AND "userId" = %s AND "expiresAt" > now()',
            (fileId, str(userId)),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    name, mime_type, data = row
    media_type = mime_type or "application/octet-stream"
    filename = name or "download"
    return Response(
        content=bytes(data),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )
