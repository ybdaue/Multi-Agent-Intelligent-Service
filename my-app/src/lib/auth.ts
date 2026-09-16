import { betterAuth } from "better-auth"
import { prismaAdapter } from "better-auth/adapters/prisma"
import prisma from "./prisma"
import { env } from "./env"

export const auth = betterAuth({
  baseURL: env.NEXT_PUBLIC_BETTER_AUTH_URL,
  database: prismaAdapter(prisma, { provider: "postgresql" }),
  emailAndPassword: { enabled: true, disableSignUp: true },
  session: {
    expiresIn: 60 * 60 * 2, // 2 小时；不写默认 7 天 (3600*24*7)
    updateAge:0,    //自动续期的冷却
    disableSessionRefresh: false,     // 开启自动续期 
  },
})