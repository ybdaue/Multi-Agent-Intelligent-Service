"use server";

import prisma from "../../prisma";
import { requireSuperAdmin, logAdminAction, revalidateAdmin } from "./shared";

export async function getModelRoutes() {
  await requireSuperAdmin();
  return prisma.modelRoute.findMany({ orderBy: [{ serviceType: "asc" }, { role: "asc" }, { modelName: "asc" }] });
}

export async function createModelRoute(data: {
  role: string; serviceType: string; provider: string; modelName: string;
  inputPrice: number; outputPrice: number; isActive?: boolean; isBackup?: boolean; priority?: number;
}) {
  const admin = await requireSuperAdmin();
  const result = await prisma.modelRoute.create({
    data: {
      role: data.role, serviceType: data.serviceType, provider: data.provider, modelName: data.modelName,
      inputPrice: data.inputPrice, outputPrice: data.outputPrice,
      isActive: data.isActive ?? true, isBackup: data.isBackup ?? false, priority: data.priority ?? 0,
    },
  });
  revalidateAdmin("/admin/pricing");
  logAdminAction({
    adminId: admin.userId, adminEmail: admin.email, action: "create", targetType: "model-route",
    targetId: result.id, detail: `新增模型路由 ${data.role}/${data.modelName}`,
  });
  return result;
}

export async function updateModelRoute(id: string, data: {
  role?: string; serviceType?: string; provider?: string; modelName?: string;
  inputPrice?: number; outputPrice?: number; isActive?: boolean; isBackup?: boolean; priority?: number;
}) {
  const admin = await requireSuperAdmin();
  const result = await prisma.modelRoute.update({ where: { id }, data });
  revalidateAdmin("/admin/pricing");
  logAdminAction({
    adminId: admin.userId, adminEmail: admin.email, action: "update", targetType: "model-route",
    targetId: id, detail: `修改模型路由 ${data.role ?? ""}`,
  });
  return result;
}

export async function deleteModelRoute(id: string) {
  const admin = await requireSuperAdmin();
  await prisma.modelRoute.delete({ where: { id } });
  revalidateAdmin("/admin/pricing");
  logAdminAction({
    adminId: admin.userId, adminEmail: admin.email, action: "delete", targetType: "model-route",
    targetId: id, detail: `删除模型路由`,
  });
}

/** 模型配置项 */
export interface ModelGroupItem {
  provider: string;
  modelName: string;
  inputPrice: number;
  outputPrice: number;
  isBackup: boolean;
  priority: number;
  isActive?: boolean;
}

/** 批量保存某个 (serviceType, role) 下的全部模型配置。先删后建，同时同步 pricing 记录。 */
export async function saveModelGroup(
  serviceType: string,
  role: string,
  models: ModelGroupItem[],
) {
  const admin = await requireSuperAdmin();

  try {
    await prisma.$transaction(async (tx) => {
      // 删旧
      await tx.modelRoute.deleteMany({ where: { serviceType, role } });

      // 建新（用 upsert 避免并发或同厂商同名冲突）
      for (const m of models) {
        await tx.modelRoute.upsert({
          where: {
            role_serviceType_provider_modelName_isBackup: {
              role, serviceType, provider: m.provider, modelName: m.modelName, isBackup: m.isBackup,
            },
          },
          update: {
            inputPrice: m.inputPrice, outputPrice: m.outputPrice,
            isActive: m.isActive ?? true, priority: m.priority,
          },
          create: {
            role, serviceType, provider: m.provider, modelName: m.modelName,
            inputPrice: m.inputPrice, outputPrice: m.outputPrice,
            isActive: m.isActive ?? true, isBackup: m.isBackup, priority: m.priority,
          },
        });

        // 同步 pricing 记录，使 billing.py 能查到价格
        await tx.modelRoute.upsert({
          where: {
            role_serviceType_provider_modelName_isBackup: {
              role: "pricing", serviceType, provider: m.provider, modelName: m.modelName, isBackup: false,
            },
          },
          update: { inputPrice: m.inputPrice, outputPrice: m.outputPrice, isActive: true },
          create: {
            role: "pricing", serviceType, provider: m.provider, modelName: m.modelName,
            inputPrice: m.inputPrice, outputPrice: m.outputPrice,
            isActive: true, isBackup: false, priority: 0,
          },
        });
      }
    });
  } catch (e: unknown) {
    throw e;
  }

  revalidateAdmin("/admin/pricing");
  logAdminAction({
    adminId: admin.userId, adminEmail: admin.email,
    action: "create", targetType: "model-route",
    targetId: `${serviceType}/${role}`, detail: `批量更新 ${serviceType}/${role}：${models.length} 条`,
  });
}