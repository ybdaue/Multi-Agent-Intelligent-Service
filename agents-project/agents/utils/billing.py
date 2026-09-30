"""Token 计费核心：per-request contextvars 累加器 + 结算逻辑。

用法：
  1. FastAPI middleware 调用 start_request_billing() 开启累加
  2. _ChatOpenAI hook 自动调用 record_llm_call() 采集
  3. Middleware finally 调用 collect_request_usage() 取走数据
  4. 调用 settle_billing() 完成定价查询 + 写入记录 + 扣费
"""

import contextvars
import math
import uuid
import datetime
from dataclasses import dataclass, field


# ── 数据结构 ─────────────────────────────────────────────────

@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMCallRecord:
    provider: str = ""
    model_name: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)


# ── contextvars 累加器 ─────────────────────────────────────

# 每个请求独立的 LLM 调用记录列表；None 表示不计费模式
_current_request_calls: contextvars.ContextVar[list[LLMCallRecord] | None] = (
    contextvars.ContextVar("_billing_calls", default=None)
)


def start_request_billing() -> None:
    """在 FastAPI 请求入口调用：建立新的空累加器。"""
    _current_request_calls.set([])


def record_llm_call(
    provider: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """由 _ChatOpenAI hook 在每次 LLM 调用完成后调用。

    如果当前不在计费请求中（context 未设或为 None），静默跳过。
    """
    calls = _current_request_calls.get()
    if calls is None:
        return  # 不计费模式（如测试/离线脚本等无 middleware 的环境）
    calls.append(
        LLMCallRecord(
            provider=provider,
            model_name=model_name,
            usage=TokenUsage(input_tokens, output_tokens),
        )
    )


def collect_request_usage() -> list[LLMCallRecord] | None:
    """在请求处理完成后调用：取走并清空累加器。

    返回 None 表示不计费模式。
    """
    calls = _current_request_calls.get()
    _current_request_calls.set(None)
    return calls


# ── 余额预检 ────────────────────────────────────────────────


async def check_user_credit(user_id: str) -> tuple[bool, str]:
    """检查用户是否有可用额度。

    如果用户有活跃套餐（剩余 token > 0），允许即使余额为负。
    如果无套餐且余额 < 0，拒绝请求。

    Returns:
        (allowed, reason)
    """
    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        # 1. 查余额
        cur = await conn.execute(
            'SELECT balance FROM "BillingAccount" WHERE "userId" = %s',
            (user_id,),
        )
        row = await cur.fetchone()
        balance = row[0] if row else 0

        if balance >= 0:
            return True, ""

        # 2. 余额为负时，检查是否有活跃套餐额度
        cur = await conn.execute(
            """SELECT up."remainingTokens"
               FROM "UserPlan" up
               WHERE up."userId" = %s
                 AND up.status = 'active'
                 AND up."remainingTokens" > 0
                 AND (up."expiresAt" IS NULL OR up."expiresAt" > now())
               LIMIT 1""",
            (user_id,),
        )
        row = await cur.fetchone()
        if row and row[0] > 0:
            return True, ""

        return False, f"余额不足（当前余额：{balance} 分），请充值后使用"


# ── 定价计算 ────────────────────────────────────────────────

MAX_RETRY = 3


def _round_up_cost(tokens: int, price_per_1m: float) -> int:
    """向上取整到分：tokens × 价格(元/百万) ÷ 10000，结果向上取整。"""
    return math.ceil(tokens * price_per_1m / 10000)


async def calculate_cost(
    conn,
    service_type: str,
    provider: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
) -> tuple[int, int, int]:
    """查 pricing_config 计算费用。查不到则 fallback 到默认价格。

    Returns:
        (input_cost, output_cost, total_cost)  单位：分
    """
    cur = await conn.execute(
        """SELECT "inputPrice", "outputPrice" FROM "ModelRoute"
         WHERE "serviceType" = %s AND "provider" = %s AND "modelName" = %s AND "isActive" = true
         ORDER BY CASE WHEN role = 'pricing' THEN 0 ELSE 1 END
         LIMIT 1""",
        (service_type, provider, model_name),
    )
    row = await cur.fetchone()
    if row:
        input_price, output_price = row
    else:
        # 默认 fallback：50 元 / 百万 input tokens, 200 元 / 百万 output tokens
        input_price, output_price = 50.0, 200.0

    input_cost = _round_up_cost(input_tokens, input_price)
    output_cost = _round_up_cost(output_tokens, output_price)
    return input_cost, output_cost, input_cost + output_cost


async def deduct_balance(
    conn,
    user_id: str,
    total_cost: int,
) -> tuple[bool, int]:
    """乐观锁扣费。

    如果用户已封禁（banned = true），跳过扣费返回 (True, 0)。
    如果用户无 BillingAccount 则自动创建（允许负余额）。
    扣费后 balance 可能为负。

    Returns:
        (success, balance_after)
    """
    # 检查是否封禁
    cur = await conn.execute(
        'SELECT banned FROM "User" WHERE id = %s', (user_id,)
    )
    row = await cur.fetchone()
    if row and row[0]:
        return True, 0  # 已封禁用户，跳过扣费

    # 查当前账户
    cur = await conn.execute(
        'SELECT balance, version FROM "BillingAccount" WHERE "userId" = %s',
        (user_id,),
    )
    row = await cur.fetchone()
    if row is None:
        # 没有账户则自动创建（允许欠费）
        await conn.execute(
            'INSERT INTO "BillingAccount" ("userId", balance, version, "updatedAt") VALUES (%s, %s, 1, now())',
            (user_id, -total_cost),
        )
        return True, -total_cost

    balance, version = row
    new_balance = balance - total_cost

    cur = await conn.execute(
        """UPDATE "BillingAccount"
           SET balance = %s, version = %s, "updatedAt" = now()
           WHERE "userId" = %s AND version = %s""",
        (new_balance, version + 1, user_id, version),
    )

    if cur.rowcount == 0:
        return False, balance  # 乐观锁冲突

    return True, new_balance


# ── 套餐 token 抵扣 ────────────────────────────────────────

async def deduct_from_plan(
    conn,
    user_id: str,
    service_type: str,
    provider: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
) -> tuple[int, int, int, str | None]:
    """查找并扣除用户活跃套餐中的 token 额度。

    扣减顺序：先 input 再 output；有多个套餐时按过期时间升序。
    如果套餐额度不足，只扣可扣部分，余量走余额。

    Returns:
        (plan_deducted_tokens, remaining_input, remaining_output, plan_id)
        plan_deducted_tokens: 从套餐扣了多少 raw token
        remaining_input: 套餐未覆盖仍需计费的 input tokens
        remaining_output: 套餐未覆盖仍需计费的 output tokens
        plan_id: 使用了哪个套餐（None 表示无可用套餐）
    """
    total_raw = input_tokens + output_tokens
    if total_raw == 0:
        return 0, 0, 0, None

    # 查用户活跃且额度充足的套餐，按过期时间升序
    cur = await conn.execute(
        """SELECT up.id, up."remainingTokens", up."totalTokens", up."usedTokens",
                  p."serviceType", p."modelName", up."expiresAt"
           FROM "UserPlan" up
           JOIN "Plan" p ON p.id = up."planId"
           WHERE up."userId" = %s
             AND up.status = 'active'
             AND up."remainingTokens" > 0
             AND (up."expiresAt" IS NULL OR up."expiresAt" > now())
             AND (p."serviceType" IS NULL OR p."serviceType" = %s)
             AND (p."modelName" IS NULL OR p."modelName" = %s)
           ORDER BY up."expiresAt" ASC NULLS LAST
           LIMIT 1""",
        (user_id, service_type, model_name),
    )
    row = await cur.fetchone()
    if not row:
        return 0, input_tokens, output_tokens, None

    plan_id = row[0]
    remaining = row[1]

    # 先扣 input，再扣 output
    deduct_input = min(input_tokens, remaining)
    still_remaining = remaining - deduct_input
    deduct_output = min(output_tokens, still_remaining)
    deducted = deduct_input + deduct_output

    # 更新套餐额度（带并发安全：WHERE remainingTokens >= deducted）
    cur = await conn.execute(
        """UPDATE "UserPlan"
           SET "usedTokens" = "usedTokens" + %s,
               "remainingTokens" = "remainingTokens" - %s
           WHERE id = %s AND "remainingTokens" >= %s""",
        (deducted, deducted, plan_id, deducted),
    )
    if cur.rowcount == 0:
        # 并发冲突，额度已被其他请求消耗→全部走余额
        return 0, input_tokens, output_tokens, None

    remaining_input = input_tokens - deduct_input
    remaining_output = output_tokens - deduct_output

    return deducted, remaining_input, remaining_output, plan_id


# ── 完整结算流程 ────────────────────────────────────────────

async def settle_billing(
    user_id: str,
    service_type: str,
    calls: list[LLMCallRecord],
    request_path: str = "",
    thread_id: str = "",
) -> None:
    """完整结算流程：遍历所有 LLM 调用 -> 查定价 -> 写 billing_record -> 套餐抵扣 -> 乐观锁扣余额。

    在 asyncio.create_task 中异步执行（不阻塞响应）。
    如果某次扣费乐观锁冲突，最多重试 MAX_RETRY 次。
    """
    if not calls:
        return

    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        for call in calls:
            plan_deducted = 0
            plan_id = None
            remaining_input = call.usage.input_tokens
            remaining_output = call.usage.output_tokens

            # 先尝试套餐抵扣
            plan_deducted, remaining_input, remaining_output, plan_id = (
                await deduct_from_plan(
                    conn,
                    user_id,
                    service_type,
                    call.provider,
                    call.model_name,
                    call.usage.input_tokens,
                    call.usage.output_tokens,
                )
            )

            # 计算套餐未覆盖部分的费用
            if remaining_input > 0 or remaining_output > 0:
                input_cost, output_cost, total_cost = await calculate_cost(
                    conn,
                    service_type,
                    call.provider,
                    call.model_name,
                    remaining_input,
                    remaining_output,
                )
            else:
                input_cost, output_cost, total_cost = 0, 0, 0

            # 乐观锁扣费（带重试）
            balance_after = 0
            if total_cost > 0:
                for attempt in range(MAX_RETRY):
                    success, balance = await deduct_balance(conn, user_id, total_cost)
                    if success:
                        balance_after = balance
                        break
                    if attempt < MAX_RETRY - 1:
                        import asyncio
                        await asyncio.sleep(0.05)
                else:
                    balance_after = 0
            else:
                # 全由套餐覆盖，查余额展示
                cur = await conn.execute(
                    'SELECT balance FROM "BillingAccount" WHERE "userId" = %s',
                    (user_id,),
                )
                row = await cur.fetchone()
                balance_after = row[0] if row else 0

            # 写 billing_record（保留完整 token 数和套餐信息）
            total_input_cost, total_output_cost, total_real_cost = await calculate_cost(
                conn,
                service_type,
                call.provider,
                call.model_name,
                call.usage.input_tokens,
                call.usage.output_tokens,
            )
            record_id = uuid.uuid4().hex
            await conn.execute(
                """INSERT INTO "BillingRecord"
                   ("id", "userId", "serviceType", "provider", "modelName",
                    "inputTokens", "outputTokens", "totalTokens",
                    "inputCost", "outputCost", "totalCost",
                    "balanceAfter", "requestPath", "threadId",
                    "planId", "planDeductedTokens", "balanceDeductedCost")
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    record_id,
                    user_id,
                    service_type,
                    call.provider,
                    call.model_name,
                    call.usage.input_tokens,
                    call.usage.output_tokens,
                    call.usage.total,
                    total_input_cost,
                    total_output_cost,
                    total_real_cost,
                    balance_after,
                    request_path,
                    thread_id,
                    plan_id,
                    plan_deducted,
                    total_cost,
                ),
            )

            # 写套餐使用明细
            if plan_id and plan_deducted > 0:
                    await conn.execute(
                        """INSERT INTO "PlanTokenUsage"
                       ("id", "userPlanId", "billingRecordId", "modelName",
                        "inputTokens", "outputTokens", "deductedTokens")
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (
                            uuid.uuid4().hex,
                            plan_id,
                            record_id,
                            call.model_name,
                            call.usage.input_tokens,
                            call.usage.output_tokens,
                            plan_deducted,
                        ),
                    )


# ── 订阅套餐自动续费 ───────────────────────────────────────

# 后台任务开关（文件顶部控制）
_ENABLE_SUBSCRIPTION_RENEWAL = True

_RENEWAL_INTERVAL = 3600  # 每小时检查一次


async def renew_subscriptions():
    """扫描已过期但开启了自动续费的订阅，从余额扣款续期。

    作为后台协程循环运行，不阻塞事件循环。
    """
    while _ENABLE_SUBSCRIPTION_RENEWAL:
        try:
            from api.utils.db import pg_pool

            async with pg_pool.connection() as conn:
                # 查出当前周期已过期的订阅（校验套餐是否仍上架 + 用户续费开关）
                cur = await conn.execute(
                    """SELECT up.id, up."userId", up."planId", p.price, p."tokenAmount", p."periodDays"
                   FROM "UserPlan" up
                   JOIN "Plan" p ON p.id = up."planId"
                   WHERE up.status = 'active'
                     AND up."autoRenew" = true
                     AND p."isActive" = true
                     AND up."currentPeriodEnd" IS NOT NULL
                     AND up."currentPeriodEnd" < now()
                     AND (up."lastRenewalAttempt" IS NULL
                          OR up."lastRenewalAttempt" < up."currentPeriodEnd")
                   LIMIT 50""",
                )
                rows = await cur.fetchall()

                for row in rows:
                    up_id, uid, pid, price, token_amount, period_days = row
                    # 标记已尝试
                    await conn.execute(
                        """UPDATE "UserPlan" SET "lastRenewalAttempt" = now() WHERE id = %s""",
                        (up_id,),
                    )

                    # 查余额
                    cur2 = await conn.execute(
                        'SELECT balance FROM "BillingAccount" WHERE "userId" = %s',
                        (uid,),
                    )
                    row2 = await cur2.fetchone()
                    balance = row2[0] if row2 else 0

                    if balance >= price:
                        # 扣款
                        await conn.execute(
                            """UPDATE "BillingAccount"
                           SET balance = balance - %s, version = version + 1, "updatedAt" = now()
                           WHERE "userId" = %s""",
                            (price, uid),
                        )
                        # 刷新周期
                        now_utc = datetime.datetime.now(datetime.timezone.utc)
                        pe = now_utc + datetime.timedelta(days=period_days)
                        await conn.execute(
                            """UPDATE "UserPlan"
                           SET "usedTokens" = 0,
                               "remainingTokens" = %s,
                               "currentPeriodStart" = %s,
                               "currentPeriodEnd" = %s,
                               "lastRenewalAttempt" = now()
                           WHERE id = %s""",
                            (token_amount, now_utc, pe, up_id),
                        )
                        # 记录续费扣款
                        await conn.execute(
                            """INSERT INTO "RechargeRecord"
                           (id, "userId", amount, "balanceBefore", "balanceAfter", note)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                            (
                                uuid.uuid4().hex,
                                uid,
                                -price,
                                balance,
                                balance - price,
                                f"订阅续费：Plan#{pid}",
                            ),
                        )
                    else:
                        # 余额不足，标记过期
                        await conn.execute(
                            """UPDATE "UserPlan" SET status = 'expired' WHERE id = %s""",
                            (up_id,),
                        )

                if rows:
                    await conn.commit()
        except Exception as exc:
            print(f"[billing] 订阅续费检查失败: {exc}")

        import asyncio
        await asyncio.sleep(_RENEWAL_INTERVAL)