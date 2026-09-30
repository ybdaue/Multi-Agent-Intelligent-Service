"use server";

import prisma from "../../prisma";
import { requireAdmin } from "./shared";

export async function getAdminAuditLogs(params?: {
  adminEmail?: string; action?: string; targetType?: string; dateFrom?: string; dateTo?: string;
  page?: number; pageSize?: number;
}) {
  await requireAdmin();
  const { adminEmail, action, targetType, dateFrom, dateTo, page = 1, pageSize = 12 } = params ?? {};
  const where: Record<string, unknown> = {};
  if (adminEmail) where.adminEmail = { contains: adminEmail };
  if (action) where.action = action;
  if (targetType) where.targetType = targetType;
  if (dateFrom || dateTo) {
    const createdAtFilter: Record<string, Date> = {};
    if (dateFrom) createdAtFilter.gte = new Date(dateFrom);
    if (dateTo) createdAtFilter.lte = new Date(dateTo + "T23:59:59.999Z");
    where.createdAt = createdAtFilter;
  }
  const [total, logs] = await Promise.all([
    prisma.adminAuditLog.count({ where }),
    prisma.adminAuditLog.findMany({
      where, orderBy: { createdAt: "desc" }, skip: (page - 1) * pageSize, take: pageSize,
    }),
  ]);
  return { total, page, pageSize, logs };
}