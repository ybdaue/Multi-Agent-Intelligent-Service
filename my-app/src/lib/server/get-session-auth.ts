import { headers } from "next/headers"
import { auth } from "@/lib/auth"
import prisma from "@/lib/prisma"

/**
 * 校验当前请求的 better-auth 会话，并返回原始 session token 与 userId，
 * 供路由转发给后端（后端据此做 Redis 校验）。
 * better-auth 的会话 cookie 形如 `rawToken.signature`，点号前即数据库 Session.token。
 */
export async function getSessionAuth(): Promise<{ token: string; userId: string } | null> {
  const h = await headers()
  const session = await auth.api.getSession({ headers: h })
  if (!session?.user?.id) return null
  const cookie = h.get("cookie") ?? ""
  const m = cookie.match(/(?:^|;\s*)(?:__Host-|__Secure-)?better-auth\.session_token=([^;]+)/)
  if (!m) return null
  const token = m[1].split(".")[0]

  // 额外检查 session 是否已被撤销
  const dbSession = await prisma.session.findUnique({ where: { token }, select: { revokedReason: true, expiresAt: true } })
  if (dbSession?.revokedReason || (dbSession && dbSession.expiresAt < new Date())) {
    return null
  }

  return { token, userId: session.user.id }
}
