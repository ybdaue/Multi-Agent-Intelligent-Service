"use server";

import prisma from "../prisma";
import { auth } from "../auth";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { env } from "../env";
import { getSessionAuth } from "./get-session-auth";

/** 获取当前登录用户 ID */
async function requireUser() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) redirect("/login");
  return session.user.id;
}

/** 当前用户的余额和当月消费概览 */
export async function getOverview() {
  const userId = await requireUser();
  const [account, monthCost] = await Promise.all([
    prisma.billingAccount.findUnique({ where: { userId }, select: { balance: true } }),
    prisma.billingRecord.aggregate({
      where: { userId, createdAt: { gte: new Date(Date.UTC(new Date().getUTCFullYear(), new Date().getUTCMonth(), 1)) } },
      _sum: { totalCost: true },
    }),
  ]);
  return {
    balance: account?.balance ?? 0,
    totalCostThisMonth: monthCost._sum.totalCost ?? 0,
  };
}

/** 当前用户的账单明细 */
export async function getRecords(
  page: number = 1,
  pageSize: number = 20,
  filters?: { dateFrom?: string; dateTo?: string; serviceType?: string; modelName?: string },
) {
  const userId = await requireUser();
  const where: Record<string, unknown> = { userId };
  if (filters?.dateFrom || filters?.dateTo) {
    const createdAt: Record<string, Date> = {};
    if (filters.dateFrom) createdAt.gte = new Date(filters.dateFrom);
    if (filters.dateTo) createdAt.lte = new Date(filters.dateTo + "T23:59:59.999Z");
    where.createdAt = createdAt;
  }
  if (filters?.serviceType) where.serviceType = filters.serviceType;
  if (filters?.modelName) where.modelName = filters.modelName;

  const [total, records] = await Promise.all([
    prisma.billingRecord.count({ where }),
    prisma.billingRecord.findMany({
      where,
      orderBy: { createdAt: "desc" },
      skip: (page - 1) * pageSize,
      take: pageSize,
      select: {
        id: true, serviceType: true, provider: true, modelName: true,
        inputTokens: true, outputTokens: true, totalTokens: true,
        inputCost: true, outputCost: true, totalCost: true,
        balanceAfter: true, requestPath: true, createdAt: true,
      },
    }),
  ]);
  return { total, records };
}

/** 当前用户的余额记录 */
export async function getRecharges(
  page: number = 1,
  pageSize: number = 20,
  filters?: { dateFrom?: string; dateTo?: string },
) {
  const userId = await requireUser();
  const where: Record<string, unknown> = { userId };
  if (filters?.dateFrom || filters?.dateTo) {
    const createdAt: Record<string, Date> = {};
    if (filters.dateFrom) createdAt.gte = new Date(filters.dateFrom);
    if (filters.dateTo) createdAt.lte = new Date(filters.dateTo + "T23:59:59.999Z");
    where.createdAt = createdAt;
  }

  const [total, recharges] = await Promise.all([
    prisma.rechargeRecord.count({ where }),
    prisma.rechargeRecord.findMany({
      where,
      orderBy: { createdAt: "desc" },
      skip: (page - 1) * pageSize,
      take: pageSize,
      select: { id: true, amount: true, balanceBefore: true, balanceAfter: true, note: true, planId: true, createdAt: true },
    }),
  ]);
  return { total, recharges };
}

// ── 套餐系统 ──

/** 获取所有上架套餐 */
export async function getActivePlans() {
  const userId = await requireUser();
  const plans = await prisma.plan.findMany({
    where: { isActive: true },
    orderBy: { sortOrder: "asc" },
  });
  return plans;
}

/** 获取当前用户的已购套餐列表 */
export async function getUserPlans() {
  const userId = await requireUser();
  return prisma.userPlan.findMany({
    where: { userId },
    orderBy: { purchasedAt: "desc" },
    include: { plan: { select: { name: true, type: true, serviceType: true, isActive: true } } },
  });
}

/** 获取当前用户活跃的套餐（可用于抵扣的） */
export async function getActiveUserPlans() {
  const userId = await requireUser();
  const now = new Date();
  return prisma.userPlan.findMany({
    where: {
      userId,
      status: "active",
      AND: [
        {
          OR: [
            { remainingTokens: { gt: 0 } },
            { totalTokens: 0 }, // 充值套餐：无 token 额度，但需展示"已生效"
          ],
        },
        {
          OR: [
            { expiresAt: null },
            { expiresAt: { gt: now } },
          ],
        },
      ],
    },
    orderBy: { expiresAt: { sort: "asc", nulls: "last" } },
    include: { plan: { select: { name: true, type: true, serviceType: true, modelName: true, isActive: true } } },
  });
}

// ── 支付订单 ──

/** 切换订阅套餐自动续费 */
export async function toggleAutoRenew(userPlanId: string, autoRenew: boolean) {
  const sessionAuth = await getSessionAuth();
  if (!sessionAuth) redirect("/login");

  const res = await fetch(`${env.NEXT_PUBLIC_API_URL}/api/billing/toggle-auto-renew`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${sessionAuth.token}`,
    },
    body: JSON.stringify({ userPlanId, autoRenew }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "操作失败" }));
    throw new Error(err.detail || "操作失败");
  }

  return await res.json();
}

/** 获取当前用户的支付订单 */
export async function getPaymentOrders(
  page: number = 1,
  pageSize: number = 20,
  filters?: { dateFrom?: string; dateTo?: string; paymentMethod?: string; status?: string },
) {
  const userId = await requireUser();
  const where: Record<string, unknown> = { userId };
  if (filters?.dateFrom || filters?.dateTo) {
    const createdAt: Record<string, Date> = {};
    if (filters.dateFrom) createdAt.gte = new Date(filters.dateFrom);
    if (filters.dateTo) createdAt.lte = new Date(filters.dateTo + "T23:59:59.999Z");
    where.createdAt = createdAt;
  }
  if (filters?.paymentMethod) where.paymentMethod = filters.paymentMethod;
  if (filters?.status) where.status = filters.status;

  const [total, orders] = await Promise.all([
    prisma.paymentOrder.count({ where }),
    prisma.paymentOrder.findMany({
      where,
      orderBy: { createdAt: "desc" },
      skip: (page - 1) * pageSize,
      take: pageSize,
    }),
  ]);
  return { total, orders };
}

/** 余额支付购买套餐（调用 Python 后端） */
export async function buyPlan(planId: string) {
  const sessionAuth = await getSessionAuth();
  if (!sessionAuth) redirect("/login");

  const res = await fetch(`${env.NEXT_PUBLIC_API_URL}/api/billing/buy-plan`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${sessionAuth.token}`,
    },
    body: JSON.stringify({ planId }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "购买失败" }));
    throw new Error(err.detail || "购买失败");
  }

  return await res.json();
}

/** 创建支付订单（线上支付用） */
export async function createPaymentOrder(planId: string, paymentMethod: string) {
  const userId = await requireUser();

  const plan = await prisma.plan.findUnique({ where: { id: planId, isActive: true } });
  if (!plan) throw new Error("套餐不存在或已下架");

  // 检查是否已有同类型的活跃套餐（recharge 可重复购买）
  if (plan.type !== "recharge") {
    const existing = await prisma.userPlan.findFirst({
      where: { userId, planId, status: "active" },
    });
    if (existing) throw new Error("已有相同套餐在使用中，无法重复购买");
  }

  const order = await prisma.paymentOrder.create({
    data: {
      userId,
      planId,
      amount: plan.price,
      paymentMethod,
      status: "pending",
      expiresAt: new Date(Date.now() + 30 * 60 * 1000), // 30 分钟过期
    },
  });
  return order;
}

/** mock 支付成功：标记订单完成 + 激活套餐 */
export async function mockPayOrder(orderId: string) {
  const userId = await requireUser();

  return await prisma.$transaction(async (tx) => {
    const order = await tx.paymentOrder.findUnique({ where: { id: orderId } });
    if (!order || order.userId !== userId) throw new Error("订单不存在");
    if (order.status !== "pending") throw new Error("订单已处理");
    if (order.expiresAt < new Date()) throw new Error("订单已过期");

    const plan = await tx.plan.findUnique({ where: { id: order.planId! } });
    if (!plan) throw new Error("套餐不存在");

    // 余额支付已在创建订单时扣过款，线上支付需要 now 扣款
    if (order.paymentMethod !== "balance") {
      const account = await tx.billingAccount.findUnique({ where: { userId } });
      const balance = account?.balance ?? 0;
      if (balance < order.amount) throw new Error("余额不足，请充值");

      await tx.billingAccount.update({
        where: { userId },
        data: { balance: { decrement: order.amount }, version: { increment: 1 } },
      });

      await tx.rechargeRecord.create({
        data: {
          userId,
          amount: -order.amount,
          balanceBefore: balance,
          balanceAfter: balance - order.amount,
          note: `线上支付购买套餐：${plan.name}`,
          planId: plan.id,
        },
      });
    }

    // 标记订单成功
    await tx.paymentOrder.update({
      where: { id: orderId },
      data: { status: "success", paidAt: new Date(), tradeNo: `mock_${Date.now()}` },
    });

    // 激活套餐
    if (plan.type === "recharge") {
      const totalAdd = plan.price + (plan.bonusAmount ?? 0);
      await tx.billingAccount.upsert({
        where: { userId },
        create: { userId, balance: totalAdd },
        update: { balance: { increment: totalAdd }, version: { increment: 1 } },
      });
      await tx.rechargeRecord.create({
        data: {
          userId,
          amount: totalAdd,
          balanceBefore: 0,
          balanceAfter: totalAdd,
          note: `购买充值套餐：${plan.name}`,
          planId: plan.id,
        },
      });
    } else {
      const now = new Date();
      let expiresAt: Date | null = null;
      if (plan.type === "token" && plan.validityDays) {
        expiresAt = new Date(now.getTime() + plan.validityDays * 86400000);
      }
      let currentPeriodStart: Date | null = null;
      let currentPeriodEnd: Date | null = null;
      if (plan.type === "subscription" && plan.periodDays) {
        currentPeriodStart = now;
        currentPeriodEnd = new Date(now.getTime() + plan.periodDays * 86400000);
      }
      await tx.userPlan.create({
        data: {
          userId,
          planId: plan.id,
          status: "active",
          totalTokens: plan.tokenAmount ?? 0,
          remainingTokens: plan.tokenAmount ?? 0,
          expiresAt,
          currentPeriodStart,
          currentPeriodEnd,
        },
      });
    }

    return { success: true };
  });
}