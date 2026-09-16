import { request, RequestError } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export const POST = withAuth(async (auth, req) => {
  try {
    const body = await req.json();

    const backendRes = await request(`${BACKEND_URL}/api/finance/agent/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth.token}` },
      body: JSON.stringify(body),
    });

    if (!backendRes.ok) {
      const errorBody = await backendRes.text().catch(() => "");
      return Response.json(
        { error: `Backend error: ${backendRes.status} ${backendRes.statusText}`, detail: errorBody },
        { status: backendRes.status },
      );
    }

    return new Response(backendRes.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
      },
    });
  } catch (err) {
    const message =
      err instanceof RequestError && err.timeout
        ? "后端响应超时"
        : "服务暂时不可用";
    return Response.json({ error: message }, { status: 503 });
  }
});
