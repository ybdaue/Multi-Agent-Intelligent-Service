import { NextRequest, NextResponse } from "next/server"

const API_AUTH_PREFIX = "/api/auth"

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl

  if (pathname.startsWith(API_AUTH_PREFIX)) {
    return NextResponse.next()
  }

  try {
    const res = await fetch(new URL("/api/auth/get-session", request.url), {
      headers: request.headers,
    })
    const session = await res.json()

    if (pathname === "/login") {
      if (session?.user) {
        return NextResponse.redirect(new URL("/home", request.url))
      }
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
