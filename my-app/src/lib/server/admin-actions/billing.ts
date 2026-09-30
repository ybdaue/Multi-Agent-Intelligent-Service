"use server";

import prisma from "../../prisma";
import { requireAdmin } from "./shared";

export async function getBillingRecords(params?: {
  email?: string;
  dateFrom?: string;
  dateTo?: string;
  serviceType?: string;
  page?: number;
  pageSize?: number;
}) {
  await requireAdmin();
  const { email, dateFrom, dateTo, serviceType, page = 1, pageSize = 12 } = params ?? {};
  const where: Record<string, unknown> = {};
  if (email) {
    where.account = { user: { email: { contains: email } } };
  }
  if (serviceType) where.serviceType = serviceType;
  if (dateFrom || dateTo) {
    const createdAtFilter: Record<string, Date> = {};
    if (dateFrom) createdAtFilter.gte = new Date(dateFrom);
    if (dateTo) createdAtFilter.lte = new Date(dateTo + "T23:59:59.999Z");
    where.createdAt = createdAtFilter;
  }

  const [total, records] = await Promise.all([
    prisma.billingRecord.count({ where }),
    prisma.billingRecord.findMany({
      where,
      orderBy: { createdAt: "desc" },
      skip: (page - 1) * pageSize,
      take: pageSize,
      select: {
        id: true, userId: true, serviceType: true, provider: true, modelName: true,
        inputTokens: true, outputTokens: true, totalTokens: true, totalCost: true,
        balanceAfter: true, balanceDeductedCost: true, planDeductedTokens: true,
        requestPath: true, createdAt: true,
        account: { select: { user: { select: { email: true, name: true } } } },
      },
    }),
  ]);
  const flatRecords = records.map((r) => ({
    ...r,
    userEmail: r.account.user.email,
    userName: r.account.user.name,
    account: undefined,
  }));
  return { total, page, pageSize, records: flatRecords };
}

export async function getRechargeRecords(params?: { email?: string; dateFrom?: string; dateTo?: string; page?: number; pageSize?: number }) {
  await requireAdmin();
  const { email, dateFrom, dateTo, page = 1, pageSize = 12 } = params ?? {};
  const where: any = {};
  if (email) {
    where.account = { user: { email: { contains: email } } };
  }
  if (dateFrom || dateTo) {
    const createdAtFilter: Record<string, Date> = {};
    if (dateFrom) createdAtFilter.gte = new Date(dateFrom);
    if (dateTo) createdAtFilter.lte = new Date(dateTo + "T23:59:59.999Z");
    where.createdAt = createdAtFilter;
  }

  const [total, records] = await Promise.all([
    prisma.rechargeRecord.count({ where }),
    prisma.rechargeRecord.findMany({
      where,
      orderBy: { createdAt: "desc" },
      skip: (page - 1) * pageSize,
      take: pageSize,
      include: {
        account: {
          select: { user: { select: { email: true, name: true } } },
        },
      },
    }),
  ]);
  const flatRecords = records.map((r) => ({
    ...r,
    userEmail: r.account.user.email,
    userName: r.account.user.name,
    account: undefined,
  }));
  return { total, page, pageSize, records: flatRecords };
}