import { request } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export const GET = withAuth(async (auth, req) => {
  const { searchParams } = new URL(req.url);
  const symbol = searchParams.get("symbol");
  if (!symbol) {
    return Response.json({ error: "缺少股票代码" }, { status: 400 });
  }

  const backendRes = await request(
    `${BACKEND_URL}/api/finance/method/tick?symbol=${encodeURIComponent(symbol)}`,
    { headers: { Authorization: `Bearer ${auth.token}` }, timeout: 15000 },
  );

  if (!backendRes.ok) {
    return Response.json(
      { error: `后端请求失败 (${backendRes.status})` },
      { status: backendRes.status },
    );
  }

  return new Response(backendRes.body, {
    headers: {
      "Content-Type":
        backendRes.headers.get("Content-Type") ?? "application/json",
    },
  });
});
