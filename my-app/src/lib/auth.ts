import { betterAuth } from "better-auth"
import { prismaAdapter } from "better-auth/adapters/prisma"
import prisma from "./prisma"
import { env } from "./env"

export const auth = betterAuth({
  baseURL: env.NEXT_PUBLIC_BETTER_AUTH_URL,
  database: prismaAdapter(prisma, { provider: "postgresql" }),
  emailAndPassword: { enabled: true, disableSignUp: true },
  session: {
    expiresIn: 60 * 60 * 2, // 2 小时
    updateAge: 0,
    disableSessionRefresh: false,
  },
  user: {
    additionalFields: {
      role: {
        type: "string",
        required: false,
        defaultValue: "user",
        input: false,
      },
    },
  },
  databaseHooks: {
    session: {
      create: {
        before: async (session) => {
          const user = await prisma.user.findUnique({ where: { id: session.userId }, select: { banned: true } })
          if (user?.banned) return false

          // 标记该用户其他活跃 session 为"被踢"
          await prisma.session.updateMany({
            where: { userId: session.userId, revokedReason: null },
            data: { revokedReason: "该账号已在其他设备登录", revokedAt: new Date() },
          })

          // 顺带清理 3 天前的死数据（过期或被撤销）
          const cutoff = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000)
          await prisma.session.deleteMany({
            where: {
              OR: [
                { revokedAt: { lt: cutoff } },
                { expiresAt: { lt: cutoff } },
              ],
            },
          })
        },
      },
    },
  },
})