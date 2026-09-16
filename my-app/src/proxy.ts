import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"

const API_AUTH_PREFIX = "/api/auth"

// 无需登录即可访问的页面
const PUBLIC_PATHS = ["/login", "/terms", "/privacy"]

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
  } catch {
    return NextResponse.redirect(new URL("/login", request.url))
  }

  return NextResponse.next()
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
}
