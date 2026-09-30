"""管理员 API：调账 / 批量调账 / 级联删除（金额相关操作保留在 Python 侧）。"""

import json
import secrets

from fastapi import APIRouter, Form, HTTPException, Request

from api.utils.db import pg_pool
from .audit import log_admin_action

router = APIRouter(prefix="/api/admin", tags=["管理员"])


async def _admin_info(request: Request) -> tuple[str, str]:
    """校验管理员身份，返回 (user_id, email)。"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT role, email FROM "User" WHERE id = %s', (user_id,)
        )
        row = await cur.fetchone()
        if not row or row[0] not in ("admin", "superAdmin"):
            raise HTTPException(status_code=403, detail="无管理员权限")
    return user_id, row[1]


async def _is_admin(request: Request) -> str:
    """仅校验管理员身份，返回 user_id（兼容 dashboard 等调用方）。"""
    uid, _ = await _admin_info(request)
    return uid


@router.post("/adjust-balance")
async def admin_adjust_balance(
    request: Request,
    userId: str = Form(...),
    amount: int = Form(...),
    note: str = Form(""),
):
    """管理员调整用户余额（正数加、负数扣）。"""
    admin_id, admin_email = await _admin_info(request)
    if amount == 0:
        raise HTTPException(status_code=400, detail="金额不能为 0")

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT balance FROM "BillingAccount" WHERE "userId" = %s',
            (userId,),
        )
        row = await cur.fetchone()
        balance_before = row[0] if row else 0
        balance_after = balance_before + amount

        await conn.execute(
            """INSERT INTO "BillingAccount" ("userId", balance, "updatedAt")
               VALUES (%s, %s, now())
               ON CONFLICT ("userId") DO UPDATE
               SET balance = "BillingAccount".balance + %s,
                   version = "BillingAccount".version + 1,
                   "updatedAt" = now()""",
            (userId, amount, amount),
        )

        record_id = "c" + secrets.token_hex(12)
        final_note = note or ("管理员调整余额" if amount >= 0 else "管理员扣款")
        await conn.execute(
            """INSERT INTO "RechargeRecord"
               (id, "userId", amount, "balanceBefore", "balanceAfter", note)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (record_id, userId, amount, balance_before, balance_after, final_note),
        )
        await conn.commit()

    action_type = "recharge" if amount > 0 else "deduct"
    await log_admin_action(
        admin_id=admin_id, admin_email=admin_email,
        action=action_type, target_type="user", target_id=userId,
        detail=f"{'充值' if amount > 0 else '扣款'} {(abs(amount) / 100):.2f} 元",
    )

    return {"balanceBefore": balance_before, "balanceAfter": balance_after}


@router.post("/batch-adjust-balance")
async def admin_batch_adjust_balance(
    request: Request,
    userIds: str = Form(...),  # JSON 字符串数组
    amount: int = Form(...),
    note: str = Form(""),
):
    """管理员批量调整用户余额（正数加、负数扣）。"""
    admin_id, admin_email = await _admin_info(request)

    uid_list = json.loads(userIds)
    if not uid_list:
        raise HTTPException(status_code=400, detail="用户列表为空")
    if amount == 0:
        raise HTTPException(status_code=400, detail="金额不能为 0")

    action_type = "recharge" if amount > 0 else "deduct"
    results = []
    async with pg_pool.connection() as conn:
        for uid in uid_list:
            cur = await conn.execute(
                'SELECT balance FROM "BillingAccount" WHERE "userId" = %s',
                (uid,),
            )
            row = await cur.fetchone()
            balance_before = row[0] if row else 0
            balance_after = balance_before + amount

            await conn.execute(
                """INSERT INTO "BillingAccount" ("userId", balance, "updatedAt")
                   VALUES (%s, %s, now())
                   ON CONFLICT ("userId") DO UPDATE
                   SET balance = "BillingAccount".balance + %s,
                       version = "BillingAccount".version + 1,
                       "updatedAt" = now()""",
                (uid, amount, amount),
            )

            record_id = "c" + secrets.token_hex(12)
            await conn.execute(
                """INSERT INTO "RechargeRecord"
                   (id, "userId", amount, "balanceBefore", "balanceAfter", note)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (record_id, uid, amount, balance_before, balance_after, note or ""),
            )
            results.append({
                "userId": uid,
                "balanceBefore": balance_before,
                "balanceAfter": balance_after,
            })

            # 逐用户记录审计日志
            await log_admin_action(
                admin_id=admin_id, admin_email=admin_email,
                action=action_type, target_type="user", target_id=uid,
                detail=f"批量{'充值' if amount > 0 else '扣款'} {(abs(amount) / 100):.2f} 元",
            )

        await conn.commit()

    return {"results": results}


@router.post("/delete-user")
async def admin_delete_user(request: Request, body: dict):
    """级联删除用户及其所有关联数据。"""
    admin_id, admin_email = await _admin_info(request)

    user_id = body.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="缺少 id")

    async with pg_pool.connection() as conn:
        # agent 相关
        await conn.execute(
            'DELETE FROM "user_session_history" WHERE "sessionId" IN (SELECT id FROM "user_session" WHERE "userId" = %s)',
            (user_id,),
        )
        await conn.execute(
            'DELETE FROM "user_session" WHERE "userId" = %s', (user_id,)
        )
        await conn.execute(
            'DELETE FROM "checkpoint" WHERE "userId" = %s', (user_id,)
        )
        await conn.execute(
            'DELETE FROM "agent_store" WHERE "userId" = %s', (user_id,)
        )

        # 计费相关
        await conn.execute(
            'DELETE FROM "PlanTokenUsage" WHERE "billingRecordId" IN (SELECT id FROM "BillingRecord" WHERE "userId" = %s)',
            (user_id,),
        )
        await conn.execute(
            'DELETE FROM "PlanTokenUsage" WHERE "userPlanId" IN (SELECT id FROM "UserPlan" WHERE "userId" = %s)',
            (user_id,),
        )
        await conn.execute(
            'DELETE FROM "UserPlan" WHERE "userId" = %s', (user_id,)
        )
        await conn.execute(
            'DELETE FROM "BillingRecord" WHERE "userId" = %s', (user_id,)
        )
        await conn.execute(
            'DELETE FROM "RechargeRecord" WHERE "userId" = %s', (user_id,)
        )
        await conn.execute(
            'DELETE FROM "BillingAccount" WHERE "userId" = %s', (user_id,)
        )

        # 文件相关
        await conn.execute(
            'DELETE FROM "temp_file" WHERE "userId" = %s', (user_id,)
        )
        await conn.execute(
            'DELETE FROM "legal_created_file" WHERE "userId" = %s', (user_id,)
        )

        await conn.execute(
            'DELETE FROM "novel" WHERE "userId" = %s', (user_id,)
        )

        # Better Auth
        await conn.execute(
            'DELETE FROM "Session" WHERE "userId" = %s', (user_id,)
        )
        await conn.execute(
            'DELETE FROM "Account" WHERE "userId" = %s', (user_id,)
        )

        # 用户本身
        await conn.execute('DELETE FROM "User" WHERE id = %s', (user_id,))
        await conn.commit()

    await log_admin_action(
        admin_id=admin_id, admin_email=admin_email,
        action="delete", target_type="user", target_id=user_id,
        detail="级联删除用户",
    )

    return {"success": True}