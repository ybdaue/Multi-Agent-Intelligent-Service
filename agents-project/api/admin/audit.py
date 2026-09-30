"""管理员操作审计日志：写入 AdminAuditLog 表。"""

import secrets

from api.utils.db import pg_pool

# 允许的操作类型
ACTIONS = {"create", "update", "delete", "ban", "unban", "publish", "archive", "recharge", "deduct"}
# 允许的目标类型
TARGET_TYPES = {"user", "novel", "chapter", "plan", "pricing", "model-route", "order", "announcement"}


async def log_admin_action(
    *,
    admin_id: str,
    admin_email: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    detail: str | None = None,
) -> None:
    """记录管理员操作到 AdminAuditLog（失败静默，不影响主流程）。"""
    if action not in ACTIONS:
        action = "update"
    if target_type not in TARGET_TYPES:
        target_type = "user"

    try:
        async with pg_pool.connection() as conn:
            record_id = "a" + secrets.token_hex(12)
            await conn.execute(
                """INSERT INTO "AdminAuditLog"
                   (id, "adminId", "adminEmail", action, "targetType", "targetId", detail, "createdAt")
                   VALUES (%s, %s, %s, %s, %s, %s, %s, now())""",
                (record_id, admin_id, admin_email, action, target_type, target_id, detail),
            )
            await conn.commit()
    except Exception:
        pass  # 日志记录失败不影响主操作