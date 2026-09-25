import { request, RequestError } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

/**
 * 这本书此刻有没有一份交了、还没确认落库的稿。
 *
 * 那一稿只活在后端的 checkpoint 里（书架列表里没有它），前端刷新 / 切书后只能靠这一问把
 * 正文、问题、按钮三样重建回来。
 */
export const GET = withAuth(async (auth, req) => {
  const novelId = req.nextUrl.searchParams.get("novelId")?.trim() ?? "";
  const chapterId = req.nextUrl.searchParams.get("chapterId")?.trim() ?? "";
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });

  const query = new URLSearchParams({ novelId });
  if (chapterId) query.set("chapterId", chapterId);

  try {
    const backendRes = await request(
      `${BACKEND_URL}/api/novel/agent/pending?${query.toString()}`,
      { headers: { Authorization: `Bearer ${auth.token}` } },
    );
    if (!backendRes.ok) {
      const detail = await backendRes.json().catch(() => null);
      const message = typeof detail?.detail === "string" ? detail.detail : "查询待确认失败";
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
