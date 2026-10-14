import type { NextRequest } from "next/server";
import { getSessionAuth } from "@/lib/server/get-session-auth";
import prisma from "@/lib/prisma";

export type AuthContext = { token: string; userId: string };

const SESSION_COOKIE_NAMES = [
  "__Host-better-auth.session_token",
  "__Secure-better-auth.session_token",
  "better-auth.session_token",
];

/** 从 request cookie 提取原始 session token */
function getToken(req: NextRequest): string | null {
  for (const name of SESSION_COOKIE_NAMES) {
    const val = req.cookies.get(name)?.value
    if (val) return val.split(".")[0]
  }
  return null
}

export function withAuth(
  handler: (auth: AuthContext, req: NextRequest) => Promise<Response> | Response,
) {
  return async (req: NextRequest): Promise<Response> => {
    const auth = await getSessionAuth();
    if (!auth) {
      // 查 DB 获取具体原因，让客户端能展示给用户
      let reason = "未登录或登录已过期，请重新登录"
      const token = getToken(req)
      if (token) {
        const s = await prisma.session.findUnique({
          where: { token },
          select: { revokedReason: true },
        })
        if (s?.revokedReason) reason = s.revokedReason
      }
      return Response.json(
        { error: reason, code: "SESSION_EXPIRED" },
        { status: 401 },
      );
    }
    const response = await handler(auth, req);
    // 续签 cookie 有效期（双保险，proxy.ts 已覆盖大部分场景）
    for (const name of SESSION_COOKIE_NAMES) {
      const val = req.cookies.get(name)?.value
      if (val) {
        response.headers.append(
          "Set-Cookie",
          `${name}=${val}; Max-Age=${60 * 60 * 2}; Path=/; HttpOnly; SameSite=Lax${
            name.startsWith("__Host-") || name.startsWith("__Secure-") || req.nextUrl.protocol === "https:"
              ? "; Secure"
              : ""
          }`,
        )
        break
      }
    }
    return response;
  };
}
