import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"

const API_AUTH_PREFIX = "/api/auth"

// 无需登录即可访问的页面
const PUBLIC_PATHS = ["/login", "/terms", "/privacy"]

// better-auth 可能使用的 cookie 名称（协议不同前缀不同）
const SESSION_COOKIE_NAMES = [
  "__Host-better-auth.session_token",
  "__Secure-better-auth.session_token",
  "better-auth.session_token",
]

function extendSessionCookie(request: NextRequest, response: NextResponse) {
  for (const name of SESSION_COOKIE_NAMES) {
    const val = request.cookies.get(name)?.value
    if (val) {
      response.cookies.set(name, val, {
        maxAge: 60 * 60 * 2, // 2 小时，滑动续期
        httpOnly: true,
        secure: request.nextUrl.protocol === "https:",
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

  try {
    // 直接读取 cookie 校验 session，避免每次请求多做一次内部 HTTP 往返
    const session = await auth.api.getSession({ headers: request.headers })

    if (pathname === "/login") {
      if (session?.user) {
        return NextResponse.redirect(new URL("/home", request.url))
      }
      return NextResponse.next()
    }

    if (PUBLIC_PATHS.includes(pathname)) {
      return NextResponse.next()
    }

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
