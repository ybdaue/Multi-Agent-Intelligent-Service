"use server";

import { randomBytes, scrypt } from "node:crypto";
import prisma from "../../prisma";
import { requireAdmin, logAdminAction, revalidateAdmin } from "./shared";

/** 用 scrypt 生成与 better-auth 兼容的密码哈希 salt:key */
function hashPassword(password: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const salt = randomBytes(16).toString("hex");
    scrypt(
      password.normalize("NFKC"),
      salt,
      64,
      { N: 16384, r: 16, p: 1, maxmem: 128 * 16384 * 16 * 2 },
      (err, key) => {
        if (err) reject(err);
        else resolve(`${salt}:${key.toString("hex")}`);
      },
    );
  });
}

type UserOrderField = "createdAt" | "email" | "name" | "balance";
type UserOrderDir = "asc" | "desc";

export async function createUser(params: {
  email: string;
  password: string;
  name?: string;
  role?: string;
}) {
  const admin = await requireAdmin();
  const { email, password, name, role = "user" } = params;

  if (!email || !password) throw new Error("邮箱和密码不能为空");
  if (admin.role === "admin" && role !== "user") {
    throw new Error("权限不足：管理员只能创建普通用户");
  }

  const existing = await prisma.user.findUnique({ where: { email } });
  if (existing) throw new Error("该邮箱已注册");

  const passwordHash = await hashPassword(password);

  const user = await prisma.$transaction(async (tx) =>
    tx.user.create({
      data: {
        email,
        name: name || null,
        role,
        emailVerified: true,
        accounts: {
          create: {
            accountId: email,
            providerId: "credential",
            password: passwordHash,
          },
        },
        billingAccount: {
          create: { balance: 0, version: 1 },
        },
      },
      select: { id: true, email: true, role: true, name: true },
    }),
  );

  revalidateAdmin("/admin/users");
  logAdminAction({
    adminId: admin.userId,
    adminEmail: admin.email,
    action: "create",
    targetType: "user",
    targetId: user.id,
    detail: `创建用户 ${email}（${role}）`,
  });

  return user;
}

export async function getUsers(params?: {
  search?: string;
  page?: number;
  pageSize?: number;
  orderField?: UserOrderField;
  orderDir?: UserOrderDir;
  role?: string;
  banned?: boolean;
  createdAtFrom?: string;
  createdAtTo?: string;
}) {
  const admin = await requireAdmin();
  const { search, page = 1, pageSize = 12, orderField = "createdAt", orderDir = "desc", role, banned, createdAtFrom, createdAtTo } = params ?? {};
  const where: Record<string, unknown> = {};
  if (search) {
    where.OR = [{ email: { contains: search } }, { name: { contains: search } }, { id: { contains: search } }];
  }
  if (role) where.role = role;
  if (banned !== undefined) where.banned = banned;
  if (createdAtFrom || createdAtTo) {
    const createdAtFilter: Record<string, Date> = {};
    if (createdAtFrom) createdAtFilter.gte = new Date(createdAtFrom);
    if (createdAtTo) createdAtFilter.lte = new Date(createdAtTo);
    where.createdAt = createdAtFilter;
  }

  const [total, users] = await Promise.all([
    prisma.user.count({ where }),
    prisma.user.findMany({
      where,
      orderBy: orderField === "balance"
        ? { billingAccount: { balance: orderDir } }
        : { [orderField]: orderDir },
      skip: (page - 1) * pageSize,
      take: pageSize,
      select: {
        id: true, email: true, name: true, role: true, banned: true, createdAt: true,
        billingAccount: { select: { balance: true } },
      },
    }),
  ]);
  return { total, page, pageSize, users, currentAdmin: { id: admin.userId, role: admin.role } };
}

export async function getUserDetail(id: string) {
  await requireAdmin();
  return prisma.user.findUnique({
    where: { id },
    select: {
      id: true, email: true, name: true, image: true, role: true, banned: true, createdAt: true,
      billingAccount: { select: { balance: true, version: true } },
      _count: { select: { novels: true, sessions: true } },
    },
  });
}

export async function banUser(id: string) {
  const admin = await requireAdmin();
  if (admin.userId === id) throw new Error("不能操作自己");

  const target = await prisma.user.findUnique({ where: { id }, select: { role: true, email: true } });
  if (!target) throw new Error("用户不存在");

  if (admin.role === "admin" && target.role !== "user") {
    throw new Error("权限不足：管理员只能封禁普通用户");
  }

  const result = await prisma.user.update({ where: { id }, data: { banned: true } });
  await prisma.session.updateMany({
    where: { userId: id, revokedReason: null },
    data: { revokedReason: "账号已被管理员封禁", revokedAt: new Date() },
  });
  revalidateAdmin("/admin/users");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "ban", targetType: "user", targetId: id, detail: `封禁用户 ${target.email || id}` });
  return result;
}

export async function unbanUser(id: string) {
  const admin = await requireAdmin();
  if (admin.userId === id) throw new Error("不能操作自己");

  const target = await prisma.user.findUnique({ where: { id }, select: { role: true } });
  if (!target) throw new Error("用户不存在");

  if (admin.role === "admin" && target.role !== "user") {
    throw new Error("权限不足：管理员只能解封普通用户");
  }

  const result = await prisma.user.update({ where: { id }, data: { banned: false } });
  revalidateAdmin("/admin/users");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "unban", targetType: "user", targetId: id, detail: `解封用户` });
  return result;
}

export async function updateUser(id: string, data: { name?: string; email?: string; role?: string }) {
  const admin = await requireAdmin();
  if (admin.userId === id) throw new Error("不能操作自己");

  const target = await prisma.user.findUnique({ where: { id }, select: { role: true } });
  if (!target) throw new Error("用户不存在");

  if (admin.role === "admin" && target.role === "superAdmin") {
    throw new Error("权限不足：管理员不能修改超级管理员");
  }

  if (data.role && admin.role === "admin" && data.role === "superAdmin") {
    throw new Error("权限不足：管理员不能将角色设为超级管理员");
  }

  const result = await prisma.user.update({ where: { id }, data });
  revalidateAdmin("/admin/users");
  logAdminAction({ adminId: admin.userId, adminEmail: admin.email, action: "update", targetType: "user", targetId: id, detail: `修改用户信息` });
  return result;
}