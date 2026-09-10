from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from api.utils.config import OUTPUT_DIR
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


@router.get("/download/{userId}/{filename:path}")
async def download_file(userId: int, filename: str):
    """下载 agent 生成的文书文件（.docx）。

    文件按 userId 隔离存放于 agent_workspace/output/{userId}/{filename}。
    """
    # 按 userId 定位目录，防止跨用户访问
    user_output_dir = (OUTPUT_DIR / str(userId)).resolve()
    if not str(user_output_dir).startswith(str(OUTPUT_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法用户 ID")

    safe_path = (user_output_dir / filename).resolve()
    if not str(safe_path).startswith(str(user_output_dir)):
        raise HTTPException(status_code=400, detail="非法文件名")

    if not safe_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    return FileResponse(
        safe_path,
        filename=safe_path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
