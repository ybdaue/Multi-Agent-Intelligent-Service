import { withAuth, type AuthContext } from "@/lib/utils/with-auth";
import type { NextRequest } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

async function handler(auth: AuthContext, req: NextRequest) {
  const targetUrl = `${BACKEND_URL}/api${req.nextUrl.pathname.replace(/^\/api/, "")}${req.nextUrl.search}`;

  const headers = new Headers(req.headers);
  headers.set("Authorization", `Bearer ${auth.token}`);
  headers.delete("host");

  try {
    const backendRes = await fetch(targetUrl, {
      method: req.method,
      headers,
      body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.blob(),
    });

    const resHeaders = new Headers(backendRes.headers);
    resHeaders.delete("host");
    resHeaders.delete("transfer-encoding");

    return new Response(backendRes.body, {
      status: backendRes.status,
      statusText: backendRes.statusText,
      headers: resHeaders,
    });
  } catch {
    return Response.json({ error: "服务暂时不可用" }, { status: 503 });
  }
}

export const GET = withAuth(handler);
export const POST = withAuth(handler);
export const PUT = withAuth(handler);
export const DELETE = withAuth(handler);
export const PATCH = withAuth(handler);