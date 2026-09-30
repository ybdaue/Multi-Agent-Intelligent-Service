/**
 * 种子脚本：为每个服务的每个功能角色配置初始主模型（qwen/deepseek-v4-flash）。
 *
 * 覆盖的 (serviceType, role) 组合：
 *   novel:   main, intent, compress
 *   legal:   main, intent, compress
 *   finance: main, intent, compress
 *   chat:    main
 *
 * 每条记录写入时会自动 upsert role=pricing 的对应记录供 billing 查询。
 *
 * 用法：cd my-app && npx tsx prisma/seed-model-routes.ts
 */
import { PrismaClient } from "../src/generated/prisma/client";
import { PrismaPg } from "@prisma/adapter-pg";

const pool = new PrismaPg({ connectionString: process.env.DATABASE_URL });
const prisma = new PrismaClient({ adapter: pool });

interface ModelItem {
  provider: string;
  modelName: string;
  inputPrice: number;
  outputPrice: number;
  isBackup: boolean;
  priority: number;
}

const PROVIDER = "qwen";
const MODEL = "deepseek-v4-flash";
const INPUT_PRICE = 50;   // 元/百万 input tokens
const OUTPUT_PRICE = 200; // 元/百万 output tokens

/** (serviceType, [roles]) */
const COMBINATIONS: [string, string[]][] = [
  ["novel", ["main", "intent", "compress"]],
  ["legal", ["main", "intent", "compress"]],
  ["finance", ["main", "intent", "compress"]],
  ["chat", ["main"]],
];

async function seedModelRoutes() {
  let total = 0;

  for (const [serviceType, roles] of COMBINATIONS) {
    for (const role of roles) {
      const model: ModelItem = {
        provider: PROVIDER,
        modelName: MODEL,
        inputPrice: INPUT_PRICE,
        outputPrice: OUTPUT_PRICE,
        isBackup: false,
        priority: 0,
      };

      await prisma.$transaction(async (tx) => {
        // 删除旧配置（先删后建，与 saveModelGroup 逻辑一致）
        await tx.modelRoute.deleteMany({ where: { serviceType, role } });

        // 创建主模型
        await tx.modelRoute.create({
          data: {
            role,
            serviceType,
            provider: model.provider,
            modelName: model.modelName,
            inputPrice: model.inputPrice,
            outputPrice: model.outputPrice,
            isActive: true,
            isBackup: model.isBackup,
            priority: model.priority,
          },
        });

        // 同步 pricing 记录
        await tx.modelRoute.upsert({
          where: {
            role_serviceType_provider_modelName_isBackup: {
              role: "pricing",
              serviceType,
              provider: model.provider,
              modelName: model.modelName,
              isBackup: false,
            },
          },
          update: {
            inputPrice: model.inputPrice,
            outputPrice: model.outputPrice,
            isActive: true,
          },
          create: {
            role: "pricing",
            serviceType,
            provider: model.provider,
            modelName: model.modelName,
            inputPrice: model.inputPrice,
            outputPrice: model.outputPrice,
            isActive: true,
            isBackup: false,
            priority: 0,
          },
        });
      });

      console.log(`  ✓ ${serviceType}/${role} → ${model.provider}/${model.modelName}`);
      total++;
    }
  }

  console.log(`\n完成：共写入 ${total} 条主模型记录 + ${total} 条 pricing 记录`);
}

seedModelRoutes()
  .catch((e) => {
    console.error("种子脚本失败:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());