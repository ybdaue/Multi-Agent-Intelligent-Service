"use server";

import prisma from "../../prisma";
import { requireAdmin, logAdminAction, revalidateAdmin } from "./shared";

export async function getPaymentOrders(params?: {
  email?: string;
  status?: string;
  paymentMethod?: string;
  dateFrom?: string;
  dateTo?: string;
  page?: number;
  pageSize?: number;
}) {
  await requireAdmin();
  const { email, status, paymentMethod, dateFrom, dateTo, page = 1, pageSize = 12 } = params ?? {};
  const where: Record<string, unknown> = {};
  if (email) where.user = { email: { contains: email } };
  if (status) where.status = status;
  if (paymentMethod) where.paymentMethod = paymentMethod;
  if (dateFrom || dateTo) {
    const createdAtFilter: Record<string, Date> = {};
    if (dateFrom) createdAtFilter.gte = new Date(dateFrom);
    if (dateTo) createdAtFilter.lte = new Date(dateTo + "T23:59:59.999Z");
    where.createdAt = createdAtFilter;
  }

  const [total, orders] = await Promise.all([
    prisma.paymentOrder.count({ where }),
    prisma.paymentOrder.findMany({
      where,
      orderBy: { createdAt: "desc" },
      skip: (page - 1) * pageSize,
      take: pageSize,
      include: {
        user: { select: { email: true, name: true } },
      },
    }),
  ]);

  const planIds = [...new Set(orders.filter((o) => o.planId).map((o) => o.planId))] as string[];
  const plans = planIds.length > 0
    ? await prisma.plan.findMany({ where: { id: { in: planIds } }, select: { id: true, name: true } })
    : [];
  const planMap = new Map(plans.map((p) => [p.id, p.name]));

  const flatOrders = orders.map((o) => ({
    ...o,
    userEmail: o.user.email,
    userName: o.user.name,
    planName: o.planId ? (planMap.get(o.planId) ?? null) : null,
    user: undefined,
  }));
  return { total, page, pageSize, orders: flatOrders };
}

export async function updatePaymentOrderStatus(id: string, status: string, note?: string) {
  const admin = await requireAdmin();
  const now = new Date();
  const data: Record<string, unknown> = { status };
  if (status === "success") data.paidAt = now;
  if (note !== undefined) data.note = note;
  const result = await prisma.paymentOrder.update({ where: { id }, data });
  revalidateAdmin("/admin/orders");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "update", targetType: "order", targetId: id, detail: `订单状态变更为 ${status}` });
  return result;
}