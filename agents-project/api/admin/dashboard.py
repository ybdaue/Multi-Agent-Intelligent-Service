"""管理员仪表盘 API：概览统计、趋势、分布、排行 + 最近消费。"""

import datetime

from fastapi import APIRouter, HTTPException, Query, Request

from api.admin.router import _is_admin
from api.utils.db import pg_pool

router = APIRouter(prefix="/api/admin/dashboard", tags=["管理员仪表盘"])


def _resolve_date_range(
    range_val: str, year: int | None = None, month: int | None = None
) -> tuple[datetime.datetime | None, datetime.datetime | None]:
    """解析时间范围参数，返回 (start, end) 元组。返回 (None, None) 表示不限。"""
    if range_val == "total":
        return None, None

    today = datetime.date.today()

    if range_val == "year":
        y = year or today.year
        start = datetime.datetime(y, 1, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(y + 1, 1, 1, tzinfo=datetime.timezone.utc)
        return start, end

    if range_val == "month":
        y = year or today.year
        m = month or today.month
        start = datetime.datetime(y, m, 1, tzinfo=datetime.timezone.utc)
        if m == 12:
            end = datetime.datetime(y + 1, 1, 1, tzinfo=datetime.timezone.utc)
        else:
            end = datetime.datetime(y, m + 1, 1, tzinfo=datetime.timezone.utc)
        return start, end

    raise HTTPException(status_code=400, detail=f"无效 range: {range_val}")


def _where_clause(
    start: datetime.datetime | None, end: datetime.datetime | None, alias: str = ""
) -> tuple[str, list]:
    """生成 SQL WHERE 子句和参数。alias 为表别名（如 "b."）。"""
    col = f'{alias}"createdAt"'
    if start and end:
        return f"WHERE {col} >= %s AND {col} < %s", [start.isoformat(), end.isoformat()]
    if start:
        return f"WHERE {col} >= %s", [start.isoformat()]
    if end:
        return f"WHERE {col} < %s", [end.isoformat()]
    return "", []


def _where_bought_clause(
    start: datetime.datetime | None, end: datetime.datetime | None
) -> tuple[str, list]:
    """生成针对 UserPlan.purchasedAt 的 WHERE 子句。"""
    col = '"purchasedAt"'
    if start and end:
        return f"WHERE {col} >= %s AND {col} < %s", [start.isoformat(), end.isoformat()]
    if start:
        return f"WHERE {col} >= %s", [start.isoformat()]
    if end:
        return f"WHERE {col} < %s", [end.isoformat()]
    return "", []


# ── 概览统计 ──


@router.get("/summary")
async def dashboard_summary(
    request: Request,
    range: str = Query("total", pattern="^(total|year|month)$"),
    year: int | None = Query(None, ge=2020, le=2100),
    month: int | None = Query(None, ge=1, le=12),
):
    """返回概览统计数据，range/year/month 控制时间范围。"""
    await _is_admin(request)
    start, end = _resolve_date_range(range, year, month)
    today_start = datetime.date.today()

    async with pg_pool.connection() as conn:
        # ── 全量计数（不受时间范围影响） ──
        cur = await conn.execute('SELECT COUNT(*) FROM "User"')
        user_count = (await cur.fetchone())[0]

        cur = await conn.execute('SELECT COUNT(*) FROM "novel"')
        novel_count = (await cur.fetchone())[0]

        cur = await conn.execute('SELECT COUNT(*) FROM "novel_chapter"')
        chapter_count = (await cur.fetchone())[0]

        # ── 时间范围筛选（范围相关统计） ──
        wh, params = _where_clause(start, end)

        if wh:
            cur = await conn.execute(
                f'SELECT COALESCE(SUM("totalCost"), 0) FROM "BillingRecord" {wh}',
                params,
            )
        else:
            cur = await conn.execute('SELECT COALESCE(SUM("totalCost"), 0) FROM "BillingRecord"')
        total_revenue = (await cur.fetchone())[0]

        if wh:
            cur = await conn.execute(
                f'SELECT COALESCE(SUM(amount), 0) FROM "RechargeRecord" {wh} AND amount > 0',
                params,
            )
        else:
            cur = await conn.execute('SELECT COALESCE(SUM(amount), 0) FROM "RechargeRecord" WHERE amount > 0')
        total_recharge = (await cur.fetchone())[0]

        if wh:
            cur = await conn.execute(
                f'SELECT COUNT(*) FROM "BillingRecord" {wh}',
                params,
            )
        else:
            cur = await conn.execute('SELECT COUNT(*) FROM "BillingRecord"')
        billing_count = (await cur.fetchone())[0]

        wh_bought, bought_params = _where_bought_clause(start, end)
        if wh_bought:
            cur = await conn.execute(
                f'SELECT COUNT(*) FROM "UserPlan" {wh_bought}',
                bought_params,
            )
        else:
            cur = await conn.execute('SELECT COUNT(*) FROM "UserPlan"')
        plan_sold = (await cur.fetchone())[0]

        # 付费用户数（有 BillingRecord 的去重 userId 数）
        if wh:
            cur = await conn.execute(
                f'SELECT COUNT(DISTINCT "userId") FROM "BillingRecord" {wh}',
                params,
            )
        else:
            cur = await conn.execute('SELECT COUNT(DISTINCT "userId") FROM "BillingRecord"')
        paid_user_count = (await cur.fetchone())[0]

        # 待处理支付订单数
        cur = await conn.execute("""SELECT COUNT(*) FROM "PaymentOrder" WHERE status = 'pending'""")
        pending_order_count = (await cur.fetchone())[0]

        # 实收收入（真金支付：排除余额支付的订单）
        pay_wh = "WHERE status = 'success' AND \"paymentMethod\" != 'balance'"
        pay_params: list = []
        if start and end:
            pay_wh += ' AND "createdAt" >= %s AND "createdAt" < %s'
            pay_params = [start.isoformat(), end.isoformat()]
        cur = await conn.execute(
            f'SELECT COALESCE(SUM(amount), 0) FROM "PaymentOrder" {pay_wh}',
            pay_params,
        )
        real_revenue = (await cur.fetchone())[0]

        # 赠送充值（充值套餐赠送金额）
        wh_bought2, bought_params2 = _where_bought_clause(start, end)
        if wh_bought2:
            cur = await conn.execute(
                f"""SELECT COALESCE(SUM(p."bonusAmount"), 0)
                    FROM "UserPlan" up
                    JOIN "Plan" p ON p.id = up."planId" AND p.type = 'recharge'
                    {wh_bought2}""",
                bought_params2,
            )
        else:
            cur = await conn.execute(
                """SELECT COALESCE(SUM(p."bonusAmount"), 0)
                   FROM "UserPlan" up
                   JOIN "Plan" p ON p.id = up."planId" AND p.type = 'recharge'"""
            )
        bonus_amount = (await cur.fetchone())[0]

        # 管理员充值（planId IS NULL AND amount > 0）
        adm_wh = 'WHERE "planId" IS NULL AND amount > 0'
        adm_params: list = []
        if start and end:
            adm_wh += ' AND "createdAt" >= %s AND "createdAt" < %s'
            adm_params = [start.isoformat(), end.isoformat()]
        cur = await conn.execute(
            f'SELECT COALESCE(SUM(amount), 0) FROM "RechargeRecord" {adm_wh}',
            adm_params,
        )
        admin_recharge = (await cur.fetchone())[0]

        # 管理员扣款（planId IS NULL AND amount < 0，取绝对值）
        adm_ded_wh = 'WHERE "planId" IS NULL AND amount < 0'
        adm_ded_params: list = []
        if start and end:
            adm_ded_wh += ' AND "createdAt" >= %s AND "createdAt" < %s'
            adm_ded_params = [start.isoformat(), end.isoformat()]
        cur = await conn.execute(
            f'SELECT COALESCE(SUM(ABS(amount)), 0) FROM "RechargeRecord" {adm_ded_wh}',
            adm_ded_params,
        )
        admin_deduction = (await cur.fetchone())[0]

        # ── 今日数据 ──
        today_str = today_start.isoformat()
        cur = await conn.execute(
            'SELECT COUNT(*) FROM "User" WHERE "createdAt" >= %s',
            (today_str,),
        )
        today_new_users = (await cur.fetchone())[0]

        cur = await conn.execute(
            'SELECT COALESCE(SUM("totalCost"), 0) FROM "BillingRecord" WHERE "createdAt" >= %s',
            (today_str,),
        )
        today_revenue = (await cur.fetchone())[0]

        cur = await conn.execute(
            'SELECT COALESCE(SUM(amount), 0) FROM "RechargeRecord" WHERE "createdAt" >= %s AND amount > 0',
            (today_str,),
        )
        today_recharge = (await cur.fetchone())[0]

    return {
        "userCount": user_count,
        "novelCount": novel_count,
        "totalChapters": chapter_count,
        "totalRevenue": total_revenue,
        "totalRecharge": total_recharge,
        "totalBillingRecords": billing_count,
        "planSoldCount": plan_sold,
        "paidUserCount": paid_user_count,
        "pendingOrderCount": pending_order_count,
        "realRevenue": real_revenue,
        "bonusAmount": bonus_amount,
        "adminRecharge": admin_recharge,
        "adminDeduction": admin_deduction,
        "todayNewUsers": today_new_users,
        "todayRevenue": today_revenue,
        "todayRecharge": today_recharge,
    }


# ── 趋势数据 ──


@router.get("/trends")
async def dashboard_trends(
    request: Request,
    range: str = Query("month", pattern="^(year|month)$"),
    year: int | None = Query(None, ge=2020, le=2100),
    month: int | None = Query(None, ge=1, le=12),
):
    """返回趋势数据。year 模式按月聚合12条，month 模式按天聚合。"""
    await _is_admin(request)
    start, end = _resolve_date_range(range, year, month)
    if start is None or end is None:
        return []

    is_year = range == "year"

    async with pg_pool.connection() as conn:
        # ── 生成日期/月份序列 ──
        if is_year:
            cur = await conn.execute(
                """SELECT to_char(d::date, 'YYYY-MM') AS dt FROM generate_series(
                    %s::date, (%s::date - interval '1 day')::date, '1 month'
                ) AS d""",
                (start.isoformat(), end.isoformat()),
            )
            date_key = "to_char(DATE_TRUNC('month', \"createdAt\")::date, 'YYYY-MM')"
            group_key = "DATE_TRUNC('month', \"createdAt\")"
        else:
            cur = await conn.execute(
                """SELECT d::date AS dt FROM generate_series(
                    %s::date, (%s::date - interval '1 day')::date, '1 day'
                ) AS d""",
                (start.isoformat(), end.isoformat()),
            )
            date_key = "DATE(\"createdAt\")"
            group_key = "DATE(\"createdAt\")"

        all_dates = [row[0] if is_year else row[0].isoformat() for row in await cur.fetchall()]

        since = start.isoformat()
        until = end.isoformat()

        # 归一化 dict key：year 模式已是字符串，month 模式 date→isoformat
        def _k(v):
            return v if is_year else v.isoformat()

        # DAU
        cur = await conn.execute(
            f"""SELECT {date_key} AS dt, COUNT(DISTINCT "userId") AS val
                FROM "BillingRecord"
                WHERE "createdAt" >= %s AND "createdAt" < %s
                GROUP BY {group_key}""",
            (since, until),
        )
        dau_map = {_k(row[0]): row[1] for row in await cur.fetchall()}

        # 登录活跃 DAU（基于 UserActivityLog）
        if is_year:
            act_date_key = "to_char(DATE_TRUNC('month', \"date\")::date, 'YYYY-MM')"
            act_group_key = "DATE_TRUNC('month', \"date\")"
        else:
            act_date_key = '"date"'
            act_group_key = '"date"'
        cur = await conn.execute(
            f"""SELECT {act_date_key} AS dt, COUNT(DISTINCT "userId") AS val
                FROM "UserActivityLog"
                WHERE "date" >= %s::date AND "date" < %s::date
                GROUP BY {act_group_key}""",
            (since, until),
        )
        login_dau_map = {_k(row[0]): row[1] for row in await cur.fetchall()}

        # 新增用户
        cur = await conn.execute(
            f"""SELECT {date_key} AS dt, COUNT(*) AS val
                FROM "User"
                WHERE "createdAt" >= %s AND "createdAt" < %s
                GROUP BY {group_key}""",
            (since, until),
        )
        new_users_map = {_k(row[0]): row[1] for row in await cur.fetchall()}

        # 收益
        cur = await conn.execute(
            f"""SELECT {date_key} AS dt, COALESCE(SUM("totalCost"), 0) AS val
                FROM "BillingRecord"
                WHERE "createdAt" >= %s AND "createdAt" < %s
                GROUP BY {group_key}""",
            (since, until),
        )
        revenue_map = {_k(row[0]): row[1] for row in await cur.fetchall()}

        # 充值
        cur = await conn.execute(
            f"""SELECT {date_key} AS dt, COALESCE(SUM(amount), 0) AS val
                FROM "RechargeRecord"
                WHERE "createdAt" >= %s AND "createdAt" < %s AND amount > 0
                GROUP BY {group_key}""",
            (since, until),
        )
        recharge_map = {_k(row[0]): row[1] for row in await cur.fetchall()}

        # 实收收入（真金支付，排除余额）
        cur = await conn.execute(
            f"""SELECT {date_key} AS dt, COALESCE(SUM(amount), 0) AS val
                FROM "PaymentOrder"
                WHERE "createdAt" >= %s AND "createdAt" < %s
                  AND status = 'success' AND "paymentMethod" != 'balance'
                GROUP BY {group_key}""",
            (since, until),
        )
        real_revenue_map = {_k(row[0]): row[1] for row in await cur.fetchall()}

        # 用户充值（planId IS NOT NULL）
        cur = await conn.execute(
            f"""SELECT {date_key} AS dt, COALESCE(SUM(amount), 0) AS val
                FROM "RechargeRecord"
                WHERE "createdAt" >= %s AND "createdAt" < %s
                  AND amount > 0 AND "planId" IS NOT NULL
                GROUP BY {group_key}""",
            (since, until),
        )
        user_recharge_map = {_k(row[0]): row[1] for row in await cur.fetchall()}

        # 管理员充值（planId IS NULL）
        cur = await conn.execute(
            f"""SELECT {date_key} AS dt, COALESCE(SUM(amount), 0) AS val
                FROM "RechargeRecord"
                WHERE "createdAt" >= %s AND "createdAt" < %s
                  AND amount > 0 AND "planId" IS NULL
                GROUP BY {group_key}""",
            (since, until),
        )
        admin_recharge_map = {_k(row[0]): row[1] for row in await cur.fetchall()}

        # 新建小说
        cur = await conn.execute(
            f"""SELECT {date_key} AS dt, COUNT(*) AS val
                FROM "novel"
                WHERE "createdAt" >= %s AND "createdAt" < %s
                GROUP BY {group_key}""",
            (since, until),
        )
        novels_map = {_k(row[0]): row[1] for row in await cur.fetchall()}

        # 新建章节
        cur = await conn.execute(
            f"""SELECT {date_key} AS dt, COUNT(*) AS val
                FROM "novel_chapter"
                WHERE "createdAt" >= %s AND "createdAt" < %s
                GROUP BY {group_key}""",
            (since, until),
        )
        chapters_map = {_k(row[0]): row[1] for row in await cur.fetchall()}

    result = []
    for d in all_dates:
        result.append({
            "date": d,
            "dau": dau_map.get(d, 0),
            "loginDau": login_dau_map.get(d, 0),
            "newUsers": new_users_map.get(d, 0),
            "revenue": revenue_map.get(d, 0),
            "recharge": recharge_map.get(d, 0),
            "realRevenue": real_revenue_map.get(d, 0),
            "userRecharge": user_recharge_map.get(d, 0),
            "adminRecharge": admin_recharge_map.get(d, 0),
            "newNovels": novels_map.get(d, 0),
            "newChapters": chapters_map.get(d, 0),
        })

    return result


# ── 服务分布 ──


@router.get("/distribution")
async def dashboard_distribution(
    request: Request,
    range: str = Query("total", pattern="^(total|year|month)$"),
    year: int | None = Query(None, ge=2020, le=2100),
    month: int | None = Query(None, ge=1, le=12),
):
    """服务类型消费统计排行（含调用次数、总费用、占比）。"""
    await _is_admin(request)
    start, end = _resolve_date_range(range, year, month)
    wh, params = _where_clause(start, end)

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            f"""SELECT "serviceType",
                       COUNT(*) AS callCount,
                       COALESCE(SUM("totalCost"), 0) AS totalCost
                FROM "BillingRecord"
                {wh}
                GROUP BY "serviceType"
                ORDER BY totalCost DESC""",
            params,
        )
        rows = await cur.fetchall()

    total = sum(row[2] for row in rows) or 1
    return [
        {
            "serviceType": row[0],
            "callCount": row[1],
            "totalCost": row[2],
            "percentage": round(row[2] / total * 100, 2),
        }
        for row in rows
    ]


# ── 用户消费 TOP10 ──


@router.get("/user-top")
async def dashboard_user_top(
    request: Request,
    range: str = Query("total", pattern="^(total|year|month)$"),
    year: int | None = Query(None, ge=2020, le=2100),
    month: int | None = Query(None, ge=1, le=12),
):
    """消费金额最高的 TOP10 用户。"""
    await _is_admin(request)
    start, end = _resolve_date_range(range, year, month)
    wh, params = _where_clause(start, end, alias="b.")

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            f"""SELECT b."userId", u.email AS userEmail, u.name AS userName,
                       COUNT(*) AS billingCount,
                       COALESCE(SUM(b."totalCost"), 0) AS totalCost
                FROM "BillingRecord" b
                LEFT JOIN "User" u ON u.id = b."userId"
                {wh}
                GROUP BY b."userId", u.email, u.name
                ORDER BY totalCost DESC
                LIMIT 10""",
            params,
        )
        rows = await cur.fetchall()

    return [
        {
            "userId": row[0],
            "userEmail": row[1],
            "userName": row[2],
            "billingCount": row[3],
            "totalCost": row[4],
        }
        for row in rows
    ]


# ── 套餐销量排行 ──


@router.get("/plan-ranking")
async def dashboard_plan_ranking(
    request: Request,
    range: str = Query("total", pattern="^(total|year|month)$"),
    year: int | None = Query(None, ge=2020, le=2100),
    month: int | None = Query(None, ge=1, le=12),
):
    """各套餐销量排行。"""
    await _is_admin(request)
    start, end = _resolve_date_range(range, year, month)
    wh, params = _where_bought_clause(start, end)

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            f"""SELECT up."planId", p.name AS planName, p.type AS planType, p.price,
                       COUNT(*) AS soldCount,
                       COUNT(*) * p.price AS totalRevenue
                FROM "UserPlan" up
                LEFT JOIN "Plan" p ON p.id = up."planId"
                {wh}
                GROUP BY up."planId", p.name, p.type, p.price
                ORDER BY soldCount DESC
                LIMIT 10""",
            params,
        )
        rows = await cur.fetchall()

    return [
        {
            "planId": row[0],
            "planName": row[1],
            "planType": row[2],
            "price": row[3],
            "soldCount": row[4],
            "totalRevenue": row[5],
        }
        for row in rows
    ]


# ── 最近消费 ──


@router.get("/recent-billing")
async def dashboard_recent_billing(
    request: Request,
    limit: int = Query(10, ge=1, le=50),
):
    """最近消费记录（含用户邮箱）。"""
    await _is_admin(request)

    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            """SELECT b.id, b."userId", u.email AS "userEmail",
                      b."serviceType", b."totalCost", b."createdAt"
               FROM "BillingRecord" b
               LEFT JOIN "User" u ON u.id = b."userId"
               ORDER BY b."createdAt" DESC
               LIMIT %s""",
            (limit,),
        )
        rows = await cur.fetchall()

    return [
        {
            "id": row[0],
            "userId": row[1],
            "userEmail": row[2],
            "serviceType": row[3],
            "totalCost": row[4],
            "createdAt": row[5].isoformat() if row[5] else None,
        }
        for row in rows
    ]


# ── AI 运营助手（预留）──


@router.post("/ai-chat")
async def dashboard_ai_chat(request: Request):
    """预留运营 AI 接口。"""
    await _is_admin(request)
    raise HTTPException(status_code=501, detail="AI 运营助手功能开发中")