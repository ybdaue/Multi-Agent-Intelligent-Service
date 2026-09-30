"use server";

import prisma from "../../prisma";
import { auth } from "../../auth";
import { headers } from "next/headers";
import { revalidatePath } from "next/cache";

/** 鉴权：必须已登录且 role 为 superAdmin，返回当前用户信息 */
export async function requireSuperAdmin() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) throw new Error("未登录");
  const role = (session.user as { role?: string }).role ?? "user";
  if (role !== "superAdmin") {
    throw new Error("无超级管理员权限");
  }
  return { userId: session.user.id, role, email: session.user.email };
}

/** 鉴权：必须已登录且 role 为 admin 或 superAdmin，返回当前用户信息 */
export async function requireAdmin() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) throw new Error("未登录");
  const role = (session.user as { role?: string }).role ?? "user";
  if (role !== "admin" && role !== "superAdmin") {
    throw new Error("无管理员权限");
  }
  return { userId: session.user.id, role, email: session.user.email };
}

/** 操作日志 */
export async function logAdminAction(params: {
  adminId: string; adminEmail: string; action: string; targetType: string; targetId?: string; detail?: string;
}) {
  try {
    await prisma.adminAuditLog.create({ data: params });
  } catch { /* 日志记录失败不影响主操作 */ }
}

/** 批量 revalidate admin 页面 */
export async function revalidateAdmin(...paths: string[]) {
  for (const p of paths) revalidatePath(p);
}