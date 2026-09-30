/**
 * 一次性脚本：从 ADMIN_EMAILS 环境变量读取管理员邮箱，设置对应用户 role = "admin"。
 * 用法：ADMIN_EMAILS=admin@example.com npx tsx prisma/seed-admin.ts
 * 迁移完成后可删除此文件。
 */
import { PrismaClient } from "../src/generated/prisma/client";
import { PrismaPg } from "@prisma/adapter-pg";

const pool = new PrismaPg({ connectionString: process.env.DATABASE_URL });
const prisma = new PrismaClient({ adapter: pool });

async function main() {
  const adminEmails = process.env.ADMIN_EMAILS?.split(",").map((s) => s.trim()).filter(Boolean) ?? [];
  if (adminEmails.length === 0) {
    console.log("ADMIN_EMAILS 未设置，跳过种子脚本。");
    console.log("如需设置管理员，请运行: ADMIN_EMAILS=xxx@example.com npx tsx prisma/seed-admin.ts");
    return;
  }

  for (const email of adminEmails) {
    const user = await prisma.user.findUnique({ where: { email } });
    if (!user) {
      console.log(`用户不存在: ${email}`);
      continue;
    }
    await prisma.user.update({ where: { email }, data: { role: "admin" } });
    console.log(`已设置管理员: ${email}`);
  }
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());