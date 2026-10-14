import { request } from "@/lib/fetch";
import type { AuthContext } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

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

/**
 * 把一张表单转给后端的某个流式口，并把 SSE 流原样透传给浏览器。
 *
 * path 是后端完整路径（`/api/novel/agent/run`、`/api/novel/setup/resume` …）—— 写章与开书
 * 两个 agent 挂在同一个大入口下面各占一段，事件协议一致，转发逻辑就这一份。
 *
 * timeout: 0 不能省：写章那一轮要等 writer 写完、reader 审完才停，默认超时会把长流掐断。
 */
export async function forwardNovelStream(
  auth: AuthContext,
  path: string,
  fields: Record<string, string>,
): Promise<Response> {
  const backendForm = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    if (value) backendForm.append(key, value);
  }

  let backendRes: Response;
  try {
    backendRes = await request(`${BACKEND_URL}${path}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${auth.token}` },
      body: backendForm,
      timeout: 0,
    });
  } catch {
    return Response.json({ error: "AI 后端服务不可用" }, { status: 502 });
  }

  if (!backendRes.ok) {
    const reason = await readBackendError(backendRes);
    return Response.json(
      { error: reason || `后端请求失败 (${backendRes.status})` },
      { status: backendRes.status },
    );
  }

  return new Response(backendRes.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
