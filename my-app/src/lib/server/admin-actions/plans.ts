"use server";

import prisma from "../../prisma";
import { requireAdmin, logAdminAction, revalidateAdmin } from "./shared";

type PlanType = "recharge" | "token" | "subscription";

export async function getPlans() {
  await requireAdmin();
  return prisma.plan.findMany({ orderBy: { sortOrder: "asc" } });
}

export async function getPlan(id: string) {
  await requireAdmin();
  return prisma.plan.findUnique({ where: { id } });
}

export async function createPlan(data: {
  name: string;
  type: PlanType;
  price: number;
  description?: string;
  bonusAmount?: number;
  tokenAmount?: number;
  serviceType?: string;
  modelName?: string;
  validityDays?: number;
  periodDays?: number;
  autoRenew?: boolean;
  sortOrder?: number;
}) {
  const admin = await requireAdmin();
  const result = await prisma.plan.create({
    data: {
      ...data,
      autoRenew: data.autoRenew ?? true,
      isActive: true,
      sortOrder: data.sortOrder ?? 0,
    },
  });
  revalidateAdmin("/admin/plans");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "create", targetType: "plan", targetId: result.id, detail: `新增套餐 ${data.name}` });
  return result;
}

export async function updatePlan(
  id: string,
  data: {
    name?: string;
    price?: number;
    description?: string;
    bonusAmount?: number;
    tokenAmount?: number;
    serviceType?: string;
    modelName?: string;
    validityDays?: number;
    periodDays?: number;
    autoRenew?: boolean;
    isActive?: boolean;
    sortOrder?: number;
  }
) {
  const admin = await requireAdmin();
  const result = await prisma.plan.update({ where: { id }, data });
  revalidateAdmin("/admin/plans");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "update", targetType: "plan", targetId: id, detail: `修改套餐` });
  return result;
}

export async function deletePlan(id: string) {
  const admin = await requireAdmin();
  await prisma.plan.delete({ where: { id } });
  revalidateAdmin("/admin/plans");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "delete", targetType: "plan", targetId: id, detail: `删除套餐` });
}

export async function getUserPlans(params?: {
  email?: string;
  dateFrom?: string;
  dateTo?: string;
  userId?: string;
  status?: string;
  type?: string;
  page?: number;
  pageSize?: number;
}) {
  await requireAdmin();
  const { email, dateFrom, dateTo, userId, status, type, page = 1, pageSize = 12 } = params ?? {};
  const where: Record<string, unknown> = {};
  if (userId) where.userId = userId;
  if (status) where.status = status;
  if (type) where.plan = { type };
  if (email) {
    where.user = { email: { contains: email } };
  }
  if (dateFrom || dateTo) {
    const purchasedAtFilter: Record<string, Date> = {};
    if (dateFrom) purchasedAtFilter.gte = new Date(dateFrom);
    if (dateTo) purchasedAtFilter.lte = new Date(dateTo + "T23:59:59.999Z");
    where.purchasedAt = purchasedAtFilter;
  }

  const [total, records] = await Promise.all([
    prisma.userPlan.count({ where }),
    prisma.userPlan.findMany({
      where,
      orderBy: { purchasedAt: "desc" },
      skip: (page - 1) * pageSize,
      take: pageSize,
      include: {
        plan: { select: { name: true, type: true, price: true } },
        user: { select: { email: true, name: true } },
      },
    }),
  ]);
  return { total, page, pageSize, records };
}