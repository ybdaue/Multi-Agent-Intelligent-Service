import { request, RequestError } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

/**
 * 这本书的对话历史。
 *
 * 对话只活在 agent 的 checkpoint 里（前端手上那份是内存里的，刷新就没），所以进页面 / 切回
 * 这本书时得问一次，拿它把右侧对话栏重建回来。一个 thread 就是一本小说，只有一个参数。
 */
export const GET = withAuth(async (auth, req) => {
  const novelId = req.nextUrl.searchParams.get("novelId")?.trim() ?? "";
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });

  try {
    const backendRes = await request(
      `${BACKEND_URL}/api/novel/agent/history?novelId=${encodeURIComponent(novelId)}`,
      { headers: { Authorization: `Bearer ${auth.token}` } },
    );
    if (!backendRes.ok) {
      const detail = await backendRes.json().catch(() => null);
      const message = typeof detail?.detail === "string" ? detail.detail : "读取对话历史失败";
      return Response.json({ error: message }, { status: backendRes.status });
    }
    return Response.json(await backendRes.json());
  } catch (err) {
    return Response.json(
      { error: err instanceof RequestError && err.timeout ? "后端响应超时" : "服务暂时不可用" },
      { status: 503 },
    );
  }
});
