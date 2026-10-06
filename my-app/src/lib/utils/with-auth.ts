import type { NextRequest } from "next/server";
import { getSessionAuth } from "@/lib/server/get-session-auth";

export type AuthContext = { token: string; userId: string };

const SESSION_COOKIE_NAMES = [
  "__Host-better-auth.session_token",
  "__Secure-better-auth.session_token",
  "better-auth.session_token",
];

export function withAuth(
  handler: (auth: AuthContext, req: NextRequest) => Promise<Response> | Response,
) {
  return async (req: NextRequest): Promise<Response> => {
    const auth = await getSessionAuth();
    if (!auth) {
      return Response.json(
        { error: "未登录或登录已过期，请重新登录" },
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
            req.nextUrl.protocol === "https:" ? "; Secure" : ""
          }`,
        )
        break
      }
    }
    return response;
  };
}
