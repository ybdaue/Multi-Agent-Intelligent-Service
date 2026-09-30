"use server";

import prisma from "../../prisma";
import { requireAdmin, logAdminAction, revalidateAdmin } from "./shared";

export async function getNovels(params?: { search?: string; page?: number; pageSize?: number; banned?: boolean }) {
  await requireAdmin();
  const { search, page = 1, pageSize = 12, banned } = params ?? {};
  const where: Record<string, unknown> = {};
  if (search) where.OR = [{ title: { contains: search } }, { id: { contains: search } }];
  if (banned !== undefined) where.banned = banned;
  const [total, novels] = await Promise.all([
    prisma.novel.count({ where }),
    prisma.novel.findMany({
      where, orderBy: { updatedAt: "desc" }, skip: (page - 1) * pageSize, take: pageSize,
      select: { id: true, title: true, wordCount: true, style: true, banned: true, createdAt: true, updatedAt: true, userId: true, _count: { select: { chapters: true, characters: true } } },
    }),
  ]);
  return { total, page, pageSize, novels };
}

export async function getNovelDetail(id: string) {
  await requireAdmin();
  return prisma.novel.findUnique({
    where: { id },
    select: {
      id: true, title: true, wordCount: true, tropes: true, style: true, banned: true, banReason: true, bannedAt: true, createdAt: true, updatedAt: true, userId: true,
      chapters: { orderBy: { order: "asc" }, select: { id: true, title: true, order: true, status: true, wordCount: true, banned: true, banReason: true, bannedAt: true, createdAt: true } },
      characters: { select: { id: true, name: true, role: true, sex: true } },
      _count: { select: { outlines: true, rules: true, timelines: true, factions: true } },
    },
  });
}

export async function updateNovel(id: string, data: { title?: string; style?: string; tropes?: string; wordCount?: number }) {
  const admin = await requireAdmin();
  const result = await prisma.novel.update({ where: { id }, data });
  revalidateAdmin("/admin/novels");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "update", targetType: "novel", targetId: id, detail: `修改小说信息` });
  return result;
}

export async function deleteNovel(id: string) {
  const admin = await requireAdmin();
  await prisma.novel.delete({ where: { id } });
  revalidateAdmin("/admin/novels");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "delete", targetType: "novel", targetId: id, detail: `删除小说` });
}

export async function banNovel(id: string, reason?: string) {
  const admin = await requireAdmin();
  const result = await prisma.novel.update({ where: { id }, data: { banned: true, banReason: reason ?? null, bannedAt: new Date() } });
  revalidateAdmin("/admin/novels");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "ban", targetType: "novel", targetId: id, detail: `封禁小说${reason ? `：${reason}` : ""}` });
  return result;
}

export async function unbanNovel(id: string) {
  const admin = await requireAdmin();
  const result = await prisma.novel.update({ where: { id }, data: { banned: false, banReason: null, bannedAt: null } });
  revalidateAdmin("/admin/novels");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "unban", targetType: "novel", targetId: id, detail: `解封小说` });
  return result;
}

export async function banChapter(id: string, reason?: string) {
  const admin = await requireAdmin();
  const result = await prisma.novel_chapter.update({ where: { id }, data: { banned: true, banReason: reason ?? null, bannedAt: new Date() } });
  revalidateAdmin("/admin/novels");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "ban", targetType: "chapter", targetId: id, detail: `封禁章节${reason ? `：${reason}` : ""}` });
  return result;
}

export async function unbanChapter(id: string) {
  const admin = await requireAdmin();
  const result = await prisma.novel_chapter.update({ where: { id }, data: { banned: false, banReason: null, bannedAt: null } });
  revalidateAdmin("/admin/novels");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "unban", targetType: "chapter", targetId: id, detail: `解封章节` });
  return result;
}