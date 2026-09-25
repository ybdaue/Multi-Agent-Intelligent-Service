import { request, RequestError } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

/**
 * 清空这本书的对话记录。
 *
 * 对话在 agent 的 checkpoint 里，所以这事只能由后端做 —— 只清前端那些气泡，一刷新又回来了。
 * 有一稿还没确认落库时后端会拒（409），把它的那句话原样交回前端显示。
 */
export const POST = withAuth(async (auth, req) => {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }

  const novelId = String(form.get("novelId") ?? "").trim();
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });

  const forwarded = new FormData();
  forwarded.append("novelId", novelId);

  try {
    const backendRes = await request(`${BACKEND_URL}/api/novel/agent/clear`, {
      method: "POST",
      body: forwarded,
      headers: { Authorization: `Bearer ${auth.token}` },
    });
    if (!backendRes.ok) {
      const detail = await backendRes.json().catch(() => null);
      const message = typeof detail?.detail === "string" ? detail.detail : "清空对话失败";
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
