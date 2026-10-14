import { NextRequest, NextResponse } from "next/server"
import prisma from "@/lib/prisma"

const COOKIE_NAMES = [
  "__Host-better-auth.session_token",
  "__Secure-better-auth.session_token",
  "better-auth.session_token",
]

/** 从 cookie 中提取 session token */
function getToken(request: NextRequest): string | null {
  for (const name of COOKIE_NAMES) {
    const val = request.cookies.get(name)?.value
    if (val) return val.split(".")[0]
  }
  return null
}

/**
 * 检查当前 session 是否已被撤销或过期。
 * 由 SessionMonitor 轮询调用，用于在客户端检测 session 状态变化。
 */
export async function GET(request: NextRequest) {
  const token = getToken(request)
  if (!token) {
    return NextResponse.json({ ok: true })
  }

  const session = await prisma.session.findUnique({
    where: { token },
    select: { revokedReason: true, expiresAt: true },
  })

  if (session?.revokedReason) {
    return NextResponse.json({ ok: false, reason: session.revokedReason })
  }

  if (session && session.expiresAt < new Date()) {
    return NextResponse.json({ ok: false, reason: "登录已过期，请重新登录" })
  }

  return NextResponse.json({ ok: true })
}