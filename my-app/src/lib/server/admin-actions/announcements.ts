"use server";

import prisma from "../../prisma";
import { requireAdmin, logAdminAction, revalidateAdmin } from "./shared";

export async function getAnnouncements(params?: { status?: string; page?: number; pageSize?: number }) {
  await requireAdmin();
  const { status, page = 1, pageSize = 12 } = params ?? {};
  const where: Record<string, unknown> = {};
  if (status) where.status = status;
  const [total, announcements] = await Promise.all([
    prisma.announcement.count({ where }),
    prisma.announcement.findMany({
      where, orderBy: { createdAt: "desc" }, skip: (page - 1) * pageSize, take: pageSize,
      include: { creator: { select: { email: true } } },
    }),
  ]);
  return { total, page, pageSize, announcements };
}

export async function createAnnouncement(data: {
  title: string; content: string; priority?: string; targetRole?: string; publishAt?: string; expiresAt?: string;
}) {
  const admin = await requireAdmin();
  const publishAt = data.publishAt ? new Date(data.publishAt) : null;
  const expiresAt = data.expiresAt ? new Date(data.expiresAt) : null;
  const now = new Date();
  const isAutoPublish = publishAt && publishAt <= now;
  const result = await prisma.announcement.create({
    data: {
      title: data.title,
      content: data.content,
      priority: data.priority ?? "normal",
      targetRole: data.targetRole ?? null,
      publishAt,
      expiresAt,
      status: isAutoPublish ? "published" : publishAt ? "draft" : "published",
      publishedAt: isAutoPublish ? now : null,
      createdBy: admin.userId,
    },
  });
  revalidateAdmin("/admin/announcements");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "create", targetType: "announcement", targetId: result.id, detail: `新建公告：${data.title}` });
  return result;
}

export async function updateAnnouncement(id: string, data: {
  title?: string; content?: string; priority?: string; targetRole?: string; publishAt?: string; expiresAt?: string;
}) {
  const admin = await requireAdmin();
  const updateData: Record<string, unknown> = { ...data };
  if (data.publishAt !== undefined) updateData.publishAt = data.publishAt ? new Date(data.publishAt) : null;
  if (data.expiresAt !== undefined) updateData.expiresAt = data.expiresAt ? new Date(data.expiresAt) : null;
  const result = await prisma.announcement.update({ where: { id }, data: updateData });
  revalidateAdmin("/admin/announcements");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "update", targetType: "announcement", targetId: id, detail: `修改公告` });
  return result;
}

export async function deleteAnnouncement(id: string) {
  const admin = await requireAdmin();
  await prisma.announcement.delete({ where: { id } });
  revalidateAdmin("/admin/announcements");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "delete", targetType: "announcement", targetId: id, detail: `删除公告` });
}

export async function publishAnnouncement(id: string) {
  const admin = await requireAdmin();
  const now = new Date();
  const result = await prisma.announcement.update({
    where: { id }, data: { status: "published", publishedAt: now, publishAt: now },
  });
  revalidateAdmin("/admin/announcements");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "publish", targetType: "announcement", targetId: id, detail: `发布公告` });
  return result;
}

export async function archiveAnnouncement(id: string) {
  const admin = await requireAdmin();
  const result = await prisma.announcement.update({
    where: { id }, data: { status: "archived" },
  });
  revalidateAdmin("/admin/announcements");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "archive", targetType: "announcement", targetId: id, detail: `下线公告` });
  return result;
}