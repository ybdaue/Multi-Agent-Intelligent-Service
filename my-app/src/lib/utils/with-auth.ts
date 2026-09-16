import type { NextRequest } from "next/server";
import { getSessionAuth } from "@/lib/server/get-session-auth";

export type AuthContext = { token: string; userId: string };

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
    return handler(auth, req);
  };
}
