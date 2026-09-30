"""计费 API：套餐购买等操作。"""

import uuid
import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.utils.db import pg_pool

router = APIRouter(prefix="/api/billing", tags=["计费"])


class BuyPlanRequest(BaseModel):
    planId: str


@router.post("/buy-plan")
async def buy_plan(request: Request, body: BuyPlanRequest):
    """余额购买套餐：校验 → 扣款 → 创建 PaymentOrder / 激活 UserPlan。"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    plan_id = body.planId

    async with pg_pool.connection() as conn:
        # 查套餐
        cur = await conn.execute(
            """SELECT "id", "name", "type", "price", "bonusAmount", "tokenAmount",
                      "serviceType", "modelName", "validityDays", "periodDays", "autoRenew"
               FROM "Plan" WHERE "id" = %s AND "isActive" = true""",
            (plan_id,),
        )
        plan = await cur.fetchone()
        if not plan:
            raise HTTPException(status_code=404, detail="套餐不存在或已下架")

        plan_name = plan[1]
        plan_type = plan[2]
        price = plan[3]
        bonus_amount = plan[4] or 0
        token_amount = plan[5] or 0
        validity_days = plan[8]
        period_days = plan[9]
        plan_auto_renew = plan[10] if len(plan) > 10 else True

        # 检查重复购买（所有套餐都禁止重复购买）
        cur = await conn.execute(
            """SELECT id FROM "UserPlan"
               WHERE "userId" = %s AND "planId" = %s AND status = 'active'
               LIMIT 1""",
            (user_id, plan_id),
        )
        existing = await cur.fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="已有相同套餐在使用中，无法重复购买")

        # 查余额
        cur = await conn.execute(
            'SELECT balance FROM "BillingAccount" WHERE "userId" = %s',
            (user_id,),
        )
        row = await cur.fetchone()
        balance = row[0] if row else 0
        if balance < price:
            raise HTTPException(status_code=400, detail="余额不足")

        balance_before = balance
        now = datetime.datetime.now(datetime.timezone.utc)

        # 创建支付订单（状态直接 success）
        order_id = uuid.uuid4().hex
        await conn.execute(
            """INSERT INTO "PaymentOrder"
               ("id", "userId", "planId", "amount", "status", "paymentMethod",
                "tradeNo", "paidAt", "expiresAt", "createdAt", "updatedAt")
               VALUES (%s, %s, %s, %s, 'success', 'balance', %s, %s, %s, %s, %s)""",
            (
                order_id, user_id, plan_id, price,
                f"balance_{uuid.uuid4().hex[:8]}",
                now,
                now + datetime.timedelta(minutes=30),
                now, now,
            ),
        )

        if plan_type == "recharge":
            # ── 充值套餐：加 bonus 到余额 ──
            total_add = price + bonus_amount
            await conn.execute(
                """INSERT INTO "BillingAccount" ("userId", balance, "updatedAt")
                   VALUES (%s, %s, now())
                   ON CONFLICT ("userId") DO UPDATE
                   SET balance = "BillingAccount".balance + %s,
                       version = "BillingAccount".version + 1,
                       "updatedAt" = now()""",
                (user_id, total_add, total_add),
            )

            await conn.execute(
                """INSERT INTO "RechargeRecord"
                   ("id", "userId", "amount", "balanceBefore", "balanceAfter", "note", "planId")
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    uuid.uuid4().hex, user_id, total_add,
                    balance_before, balance_before + total_add,
                    f"购买充值套餐：{plan_name}", plan_id,
                ),
            )

            # 充值套餐也写入 UserPlan（控制台统一展示用，无 token 额度）
            await conn.execute(
                """INSERT INTO "UserPlan"
                   ("id", "userId", "planId", "status", "totalTokens", "remainingTokens",
                    "purchasedAt")
                   VALUES (%s, %s, %s, 'active', 0, 0, %s)""",
                (uuid.uuid4().hex, user_id, plan_id, now),
            )
        else:
            # ── Token / 订阅套餐：扣余额 + 创建 UserPlan ──
            balance_after = balance_before - price
            await conn.execute(
                """UPDATE "BillingAccount"
                   SET balance = %s, version = version + 1, "updatedAt" = now()
                   WHERE "userId" = %s AND balance >= %s""",
                (balance_after, user_id, price),
            )

            await conn.execute(
                """INSERT INTO "RechargeRecord"
                   ("id", "userId", "amount", "balanceBefore", "balanceAfter", "note", "planId")
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    uuid.uuid4().hex, user_id, -price,
                    balance_before, balance_after,
                    f"购买{'Token' if plan_type == 'token' else '订阅'}套餐：{plan_name}",
                    plan_id,
                ),
            )

            # 计算有效期
            expires_at = None
            if plan_type == "token" and validity_days:
                expires_at = now + datetime.timedelta(days=validity_days)

            current_period_start = None
            current_period_end = None
            if plan_type == "subscription" and period_days:
                current_period_start = now
                current_period_end = now + datetime.timedelta(days=period_days)

            await conn.execute(
                """INSERT INTO "UserPlan"
                   ("id", "userId", "planId", "status", "totalTokens", "remainingTokens",
                    "expiresAt", "currentPeriodStart", "currentPeriodEnd", "purchasedAt",
                    "autoRenew")
                   VALUES (%s, %s, %s, 'active', %s, %s, %s, %s, %s, %s, %s)""",
                (
                    uuid.uuid4().hex, user_id, plan_id,
                    token_amount, token_amount,
                    expires_at, current_period_start, current_period_end, now,
                    plan_auto_renew,
                ),
            )

        await conn.commit()

    return {"success": True}


class ToggleAutoRenewRequest(BaseModel):
    userPlanId: str
    autoRenew: bool


@router.post("/toggle-auto-renew")
async def toggle_auto_renew(request: Request, body: ToggleAutoRenewRequest):
    """切换用户套餐的自动续费开关。"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    async with pg_pool.connection() as conn:
        # 校验套餐归属 + 套餐仍上架
        cur = await conn.execute(
            """SELECT up.id FROM "UserPlan" up
               JOIN "Plan" p ON p.id = up."planId"
               WHERE up.id = %s AND up."userId" = %s
                 AND p.type = 'subscription' AND p."isActive" = true""",
            (body.userPlanId, user_id),
        )
        if not await cur.fetchone():
            raise HTTPException(status_code=400, detail="套餐不存在或已下架，无法修改续费设置")

        await conn.execute(
            'UPDATE "UserPlan" SET "autoRenew" = %s WHERE id = %s',
            (body.autoRenew, body.userPlanId),
        )
        await conn.commit()

    return {"success": True}