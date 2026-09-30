"use server";

import prisma from "../prisma";

/** 获取对普通用户可见的已发布公告（首页滚动播放用） */
export async function getActiveAnnouncements() {
  const now = new Date();
  const announcements = await prisma.announcement.findMany({
    where: {
      status: "published",
      AND: [
        { OR: [{ publishAt: null }, { publishAt: { lte: now } }] },
        { OR: [{ expiresAt: null }, { expiresAt: { gt: now } }] },
        { OR: [{ targetRole: null }, { targetRole: "user" }] },
      ],
    },
    orderBy: [{ priority: "desc" }, { publishedAt: "desc" }],
    select: { id: true, title: true, content: true, priority: true, publishedAt: true },
  });
  return announcements;
}