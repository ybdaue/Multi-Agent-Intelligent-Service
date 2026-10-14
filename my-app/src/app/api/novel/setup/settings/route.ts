import { request, RequestError } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

/**
 * 开书图当前收集的设定状态（从 checkpoint 读取，不修改任何数据）。
 *
 * 书架没有这一份快照，弹窗右侧面板靠它展示六项设定的收集进度与可读内容。
 * 每次 SSE question / final 事件后自动拉取。checkpoint 还没建起来时返回全空状态。
 */
export const GET = withAuth(async (auth, req) => {
  const novelId = req.nextUrl.searchParams.get("novelId")?.trim() ?? "";
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });

  try {
    const backendRes = await request(
      `${BACKEND_URL}/api/novel/setup/settings?novelId=${encodeURIComponent(novelId)}`,
      { headers: { Authorization: `Bearer ${auth.token}` } },
    );
    if (!backendRes.ok) {
      const detail = await backendRes.json().catch(() => null);
      const message = typeof detail?.detail === "string" ? detail.detail : "查询设定失败";
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