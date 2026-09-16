import { request } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

function hashUserId(id: string): number {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return hash;
}

async function readBackendError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    const msg = data?.error ?? data?.detail ?? data?.message;
    if (typeof msg === "string" && msg) return msg;
    if (Array.isArray(msg)) {
      return msg.map((m) => m?.msg ?? JSON.stringify(m)).join("; ");
    }
    if (msg != null) return JSON.stringify(msg);
  } catch {
    // 非 JSON 响应，回退到原文
  }
  const text = await res.text().catch(() => "");
  return text.trim();
}

export const GET = withAuth(async (auth, req) => {
  const { searchParams } = new URL(req.url);
  const userId = hashUserId(auth.userId);

  const query = new URLSearchParams();
  query.set("userId", String(userId));
  query.set("page", searchParams.get("page") ?? "1");
  query.set("page_size", searchParams.get("pageSize") ?? "20");

  let backendRes: Response;
  try {
    backendRes = await request(
      `${BACKEND_URL}/api/legal/method/sessions?${query.toString()}`,
      { headers: { Authorization: `Bearer ${auth.token}` }, timeout: 30000 },
    );
  } catch {
    return Response.json({ error: "后端服务不可用" }, { status: 502 });
  }

  if (!backendRes.ok) {
    const reason = await readBackendError(backendRes);
    return Response.json(
      { error: reason || `后端请求失败 (${backendRes.status})` },
      { status: backendRes.status },
    );
  }

  const data = await backendRes.json().catch(() => null);
  if (!data) {
    return Response.json({ error: "后端返回格式错误" }, { status: 502 });
  }
  return Response.json(data);
});

export const DELETE = withAuth(async (auth, req) => {
  const { searchParams } = new URL(req.url);
  const threadId = searchParams.get("threadId");
  if (!threadId) {
    return Response.json({ error: "缺少会话 ID" }, { status: 400 });
  }

  const userId = hashUserId(auth.userId);
  const query = new URLSearchParams();
  query.set("userId", String(userId));
  query.set("threadId", threadId);

  let backendRes: Response;
  try {
    backendRes = await request(
      `${BACKEND_URL}/api/legal/method/sessions?${query.toString()}`,
      {
        method: "DELETE",
        headers: { Authorization: `Bearer ${auth.token}` },
        timeout: 30000,
      },
    );
  } catch {
    return Response.json({ error: "后端服务不可用" }, { status: 502 });
  }

  if (!backendRes.ok) {
    const reason = await readBackendError(backendRes);
    return Response.json(
      { error: reason || `后端请求失败 (${backendRes.status})` },
      { status: backendRes.status },
    );
  }

  const data = await backendRes.json().catch(() => null);
  if (!data) {
    return Response.json({ error: "后端返回格式错误" }, { status: 502 });
  }
  return Response.json(data);
});
