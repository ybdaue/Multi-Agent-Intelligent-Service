import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import prisma from "@/lib/prisma"

const API_AUTH_PREFIX = "/api/auth"

// 无需登录即可访问的页面
const PUBLIC_PATHS = ["/login", "/terms", "/privacy"]

// better-auth 可能使用的 cookie 名称（协议不同前缀不同）
const SESSION_COOKIE_NAMES = [
  "__Host-better-auth.session_token",
  "__Secure-better-auth.session_token",
  "better-auth.session_token",
]

/** 从 request cookie 中提取原始 session token */
function getTokenFromRequest(request: NextRequest): string | null {
  for (const name of SESSION_COOKIE_NAMES) {
    const val = request.cookies.get(name)?.value
    if (val) return val.split(".")[0]
  }
  return null
}

/** 带 __Host-/__Secure- 前缀的 cookie 必须带 Secure，否则浏览器会拒绝写入/删除 */
function needsSecure(name: string): boolean {
  return name.startsWith("__Host-") || name.startsWith("__Secure-")
}

/** 清除所有可能的 session cookie（重定向到登录页时用，防止残留 cookie 引发死循环） */
function clearSessionCookies(response: NextResponse) {
  for (const name of SESSION_COOKIE_NAMES) {
    response.cookies.set(name, "", {
      maxAge: 0,
      path: "/",
      httpOnly: true,
      sameSite: "lax",
      secure: needsSecure(name),
    })
  }
}

/** 创建重定向响应，同时清除旧 session cookie 防止重定向循环 */
function redirectToLogin(request: NextRequest, reason: string): NextResponse {
  const url = new URL(`/login?reason=${encodeURIComponent(reason)}`, request.url)
  const response = NextResponse.redirect(url)
  clearSessionCookies(response)
  return response
}

function extendSessionCookie(request: NextRequest, response: NextResponse) {
  for (const name of SESSION_COOKIE_NAMES) {
    const val = request.cookies.get(name)?.value
    if (val) {
      response.cookies.set(name, val, {
        maxAge: 60 * 60 * 2, // 2 小时，滑动续期
        httpOnly: true,
        // 带前缀的 cookie 必须 Secure；容器在 nginx 后看到的可能是 http，故以 cookie 名为准
        secure: needsSecure(name) || request.nextUrl.protocol === "https:",
        sameSite: "lax",
        path: "/",
      })
      return
    }
  }
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl

  if (pathname.startsWith(API_AUTH_PREFIX)) {
    return NextResponse.next()
  }

  // 先查 DB 预检 session 是否已被撤销或过期
  const token = getTokenFromRequest(request)

  // /login 单独处理：绝不能把 /login 再重定向到 /login，否则被踢用户会陷入死循环
  if (pathname === "/login") {
    if (token) {
      const dbSession = await prisma.session.findUnique({ where: { token } })
      // 带着已撤销/过期的 cookie 访问登录页：清掉 cookie 后就地渲染登录页
      if (dbSession?.revokedReason || (dbSession && dbSession.expiresAt < new Date())) {
        const response = NextResponse.next()
        clearSessionCookies(response)
        return response
      }
    }
    const session = await auth.api.getSession({ headers: request.headers })
    if (session?.user) {
      return NextResponse.redirect(new URL("/home", request.url))
    }
    return NextResponse.next()
  }

  if (PUBLIC_PATHS.includes(pathname)) {
    return NextResponse.next()
  }

  if (token) {
    const dbSession = await prisma.session.findUnique({ where: { token } })
    if (dbSession?.revokedReason) {
      return redirectToLogin(request, dbSession.revokedReason)
    }
    if (dbSession && dbSession.expiresAt < new Date()) {
      return redirectToLogin(request, "登录已过期，请重新登录")
    }
  }

  try {
    const session = await auth.api.getSession({ headers: request.headers })

    if (!session?.user) {
      return NextResponse.redirect(new URL("/login", request.url))
    }

    // 会话有效 → 给浏览器续 cookie 有效期，实现无感滑动续期
    const response = NextResponse.next()
    extendSessionCookie(request, response)
    return response

  } catch {
    return NextResponse.redirect(new URL("/login", request.url))
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
}