"use server";

import prisma from "../../prisma";
import { requireAdmin } from "./shared";

// ── 仪表盘概览 ──

export async function getStats() {
  await requireAdmin();
  const today = new Date();
  const todayStart = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
  const [userCount, novelCount, billingCount, totalRevenue, recentBilling, rechargesTotal, totalChapters, totalTokens, legalConversations, todayNewUsers, todayRevenue, todayRecharge] =
    await Promise.all([
      prisma.user.count(),
      prisma.novel.count(),
      prisma.billingRecord.count(),
      prisma.billingRecord.aggregate({ _sum: { totalCost: true } }),
      prisma.billingRecord.findMany({
        take: 10,
        orderBy: { createdAt: "desc" },
        select: { id: true, userId: true, serviceType: true, totalCost: true, createdAt: true },
      }),
      prisma.rechargeRecord.aggregate({ _sum: { amount: true } }),
      prisma.novel_chapter.count(),
      prisma.billingRecord.aggregate({ _sum: { totalTokens: true } }),
      prisma.billingRecord.count({ where: { serviceType: "legal" } }),
      prisma.user.count({ where: { createdAt: { gte: todayStart } } }),
      prisma.billingRecord.aggregate({ where: { createdAt: { gte: todayStart } }, _sum: { totalCost: true } }),
      prisma.rechargeRecord.aggregate({ where: { createdAt: { gte: todayStart } }, _sum: { amount: true } }),
    ]);
  return {
    userCount, novelCount, totalChapters, billingCount,
    totalRevenue: totalRevenue._sum.totalCost ?? 0,
    rechargesTotal: rechargesTotal._sum.amount ?? 0,
    totalTokens: totalTokens._sum.totalTokens ?? 0,
    legalConversations, todayNewUsers,
    todayRevenue: todayRevenue._sum.totalCost ?? 0,
    todayRecharge: todayRecharge._sum.amount ?? 0,
    recentBilling,
  };
}

// ── 消费趋势 ──

export async function getBillingTrend(days: number = 14) {
  await requireAdmin();
  const since = new Date(Date.now() - days * 86400000);
  const records = await prisma.billingRecord.findMany({
    where: { createdAt: { gte: since } },
    select: { totalCost: true, createdAt: true },
    orderBy: { createdAt: "asc" },
  });
  const map = new Map<string, number>();
  for (const r of records) {
    const day = r.createdAt.toISOString().slice(0, 10);
    map.set(day, (map.get(day) ?? 0) + r.totalCost);
  }
  const days_list: { date: string; cost: number }[] = [];
  for (let i = 0; i < days; i++) {
    const d = new Date(since.getTime() + i * 86400000);
    const key = d.toISOString().slice(0, 10);
    days_list.push({ date: key, cost: map.get(key) ?? 0 });
  }
  return days_list;
}

// ── 用户注册趋势 ──

export async function getUserRegistrationTrend(days: number = 14) {
  await requireAdmin();
  const since = new Date(Date.now() - days * 86400000);
  const users = await prisma.user.findMany({
    where: { createdAt: { gte: since } },
    select: { createdAt: true },
    orderBy: { createdAt: "asc" },
  });
  const map = new Map<string, number>();
  for (const u of users) {
    const day = u.createdAt.toISOString().slice(0, 10);
    map.set(day, (map.get(day) ?? 0) + 1);
  }
  const result: { date: string; count: number }[] = [];
  for (let i = 0; i < days; i++) {
    const d = new Date(since.getTime() + i * 86400000);
    const key = d.toISOString().slice(0, 10);
    result.push({ date: key, count: map.get(key) ?? 0 });
  }
  return result;
}

// ── 日活用户趋势 ──

export async function getDailyActiveUsers(days: number = 14) {
  await requireAdmin();
  const since = new Date(Date.now() - days * 86400000);
  const records = await prisma.billingRecord.findMany({
    where: { createdAt: { gte: since } },
    select: { userId: true, createdAt: true },
    orderBy: { createdAt: "asc" },
  });
  const map = new Map<string, Set<string>>();
  for (const r of records) {
    const day = r.createdAt.toISOString().slice(0, 10);
    if (!map.has(day)) map.set(day, new Set());
    map.get(day)!.add(r.userId);
  }
  const result: { date: string; dau: number }[] = [];
  for (let i = 0; i < days; i++) {
    const d = new Date(since.getTime() + i * 86400000);
    const key = d.toISOString().slice(0, 10);
    result.push({ date: key, dau: map.get(key)?.size ?? 0 });
  }
  return result;
}

// ── 小说创建趋势 ──

export async function getNovelCreationTrend(days: number = 14) {
  await requireAdmin();
  const since = new Date(Date.now() - days * 86400000);
  const novels = await prisma.novel.findMany({
    where: { createdAt: { gte: since } },
    select: { createdAt: true },
    orderBy: { createdAt: "asc" },
  });
  const map = new Map<string, number>();
  for (const n of novels) {
    const day = n.createdAt.toISOString().slice(0, 10);
    map.set(day, (map.get(day) ?? 0) + 1);
  }
  const result: { date: string; newNovels: number }[] = [];
  for (let i = 0; i < days; i++) {
    const d = new Date(since.getTime() + i * 86400000);
    const key = d.toISOString().slice(0, 10);
    result.push({ date: key, newNovels: map.get(key) ?? 0 });
  }
  return result;
}

// ── 章节创建趋势 ──

export async function getChapterCreationTrend(days: number = 14) {
  await requireAdmin();
  const since = new Date(Date.now() - days * 86400000);
  const chapters = await prisma.novel_chapter.findMany({
    where: { createdAt: { gte: since } },
    select: { createdAt: true },
    orderBy: { createdAt: "asc" },
  });
  const map = new Map<string, number>();
  for (const c of chapters) {
    const day = c.createdAt.toISOString().slice(0, 10);
    map.set(day, (map.get(day) ?? 0) + 1);
  }
  const result: { date: string; newChapters: number }[] = [];
  for (let i = 0; i < days; i++) {
    const d = new Date(since.getTime() + i * 86400000);
    const key = d.toISOString().slice(0, 10);
    result.push({ date: key, newChapters: map.get(key) ?? 0 });
  }
  return result;
}

// ── 活跃小说排行 ──

export async function getActiveNovelsOnDate(date: string, limit: number = 20) {
  await requireAdmin();
  const dateStart = new Date(`${date}T00:00:00.000Z`);
  const dateEnd = new Date(`${date}T23:59:59.999Z`);
  const chapters = await prisma.novel_chapter.groupBy({
    by: ["novelId"],
    _count: { id: true },
    where: { createdAt: { gte: dateStart, lte: dateEnd } },
    orderBy: { _count: { id: "desc" } },
    take: limit,
  });
  if (chapters.length === 0) return [];
  const novelIds = chapters.map((c) => c.novelId);
  const novels = await prisma.novel.findMany({
    where: { id: { in: novelIds } },
    select: { id: true, title: true, userId: true },
  });
  const userIds = [...new Set(novels.map((n) => n.userId))];
  const users = userIds.length > 0
    ? await prisma.user.findMany({ where: { id: { in: userIds } }, select: { id: true, email: true } })
    : [];
  const userMap = new Map(users.map((u) => [u.id, u.email]));
  const novelMap = new Map(novels.map((n) => [n.id, n]));
  return chapters.map((c) => ({
    novelId: c.novelId,
    title: novelMap.get(c.novelId)?.title ?? "",
    chaptersCreated: c._count.id,
    userId: novelMap.get(c.novelId)?.userId ?? "",
    userEmail: userMap.get(novelMap.get(c.novelId)?.userId ?? "") ?? "",
  }));
}

// ── 消费分布 ──

export async function getBillingServiceDistribution(days: number = 30) {
  await requireAdmin();
  const since = new Date(Date.now() - days * 86400000);
  const distribution = await prisma.billingRecord.groupBy({
    by: ["serviceType"],
    _sum: { totalCost: true },
    where: { createdAt: { gte: since } },
  });
  const total = distribution.reduce((sum, d) => sum + (d._sum.totalCost ?? 0), 0);
  return distribution.map((d) => ({
    serviceType: d.serviceType,
    totalCost: d._sum.totalCost ?? 0,
    percentage: total > 0 ? Math.round(((d._sum.totalCost ?? 0) / total) * 10000) / 100 : 0,
  }));
}

// ── 用户消费排行 ──

export async function getUserBillingRanking(days: number = 30, limit: number = 20) {
  await requireAdmin();
  const since = new Date(Date.now() - days * 86400000);
  const rows = await prisma.$queryRaw<{ id: string; email: string; name: string | null; totalCost: number; recordCount: number }[]>`
    SELECT u.id, u.email, u.name, COALESCE(SUM(b."totalCost"), 0)::int as "totalCost", COUNT(b.id)::int as "recordCount"
    FROM "User" u
    LEFT JOIN "BillingRecord" b ON b."userId" = u.id AND b."createdAt" >= ${since}
    GROUP BY u.id, u.email, u.name
    HAVING COUNT(b.id) > 0
    ORDER BY "totalCost" DESC
    LIMIT ${limit}
  `;
  return rows;
}

// ── 充值趋势 ──

export async function getRechargeTrend(days: number = 14) {
  await requireAdmin();
  const since = new Date(Date.now() - days * 86400000);
  const records = await prisma.rechargeRecord.findMany({
    where: { createdAt: { gte: since } },
    select: { amount: true, createdAt: true },
    orderBy: { createdAt: "asc" },
  });
  const map = new Map<string, { amount: number; count: number }>();
  for (const r of records) {
    const day = r.createdAt.toISOString().slice(0, 10);
    const entry = map.get(day) ?? { amount: 0, count: 0 };
    entry.amount += r.amount;
    entry.count += 1;
    map.set(day, entry);
  }
  const result: { date: string; amount: number; count: number }[] = [];
  for (let i = 0; i < days; i++) {
    const d = new Date(since.getTime() + i * 86400000);
    const key = d.toISOString().slice(0, 10);
    result.push({ date: key, amount: map.get(key)?.amount ?? 0, count: map.get(key)?.count ?? 0 });
  }
  return result;
}

// ── 用户充值排行 ──

export async function getUserRechargeRanking(days: number = 30, limit: number = 20) {
  await requireAdmin();
  const since = new Date(Date.now() - days * 86400000);
  const rows = await prisma.$queryRaw<{ id: string; email: string; name: string | null; totalAmount: number; recordCount: number }[]>`
    SELECT u.id, u.email, u.name, COALESCE(SUM(r.amount), 0)::int as "totalAmount", COUNT(r.id)::int as "recordCount"
    FROM "User" u
    INNER JOIN "RechargeRecord" r ON r."userId" = u.id AND r."createdAt" >= ${since}
    GROUP BY u.id, u.email, u.name
    ORDER BY "totalAmount" DESC
    LIMIT ${limit}
  `;
  return rows;
}

// ── 法律咨询趋势 ──

export async function getLegalConversationTrend(days: number = 14) {
  await requireAdmin();
  const since = new Date(Date.now() - days * 86400000);
  const records = await prisma.billingRecord.findMany({
    where: { serviceType: "legal", createdAt: { gte: since } },
    select: { userId: true, createdAt: true },
    orderBy: { createdAt: "asc" },
  });
  const map = new Map<string, { conversationCount: number; users: Set<string> }>();
  for (const r of records) {
    const day = r.createdAt.toISOString().slice(0, 10);
    if (!map.has(day)) map.set(day, { conversationCount: 0, users: new Set() });
    const entry = map.get(day)!;
    entry.conversationCount += 1;
    entry.users.add(r.userId);
  }
  const result: { date: string; conversationCount: number; distinctUsers: number }[] = [];
  for (let i = 0; i < days; i++) {
    const d = new Date(since.getTime() + i * 86400000);
    const key = d.toISOString().slice(0, 10);
    result.push({ date: key, conversationCount: map.get(key)?.conversationCount ?? 0, distinctUsers: map.get(key)?.users.size ?? 0 });
  }
  return result;
}

// ── 法律活跃用户 ──

export async function getLegalActiveUsers(days: number = 30, limit: number = 20) {
  await requireAdmin();
  const since = new Date(Date.now() - days * 86400000);
  const rows = await prisma.$queryRaw<{ id: string; email: string; conversationCount: number; totalCost: number }[]>`
    SELECT u.id, u.email, COUNT(b.id)::int as "conversationCount", COALESCE(SUM(b."totalCost"), 0)::int as "totalCost"
    FROM "User" u
    INNER JOIN "BillingRecord" b ON b."userId" = u.id AND b."serviceType" = 'legal' AND b."createdAt" >= ${since}
    GROUP BY u.id, u.email
    ORDER BY "conversationCount" DESC
    LIMIT ${limit}
  `;
  return rows;
}