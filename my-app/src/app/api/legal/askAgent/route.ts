import { request } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

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

export const POST = withAuth(async (auth, req) => {
  // 解析客户端 multipart 表单
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }
  const threadId = String(form.get("threadId") ?? "").trim();
  const text = String(form.get("text") ?? "").trim();
  const file = form.get("file");

  if (!text) {
    return Response.json({ error: "文本不能为空" }, { status: 400 });
  }

  // 构造后端表单并转发到 /legalAgent（直连 legal_agent 编排图）；threadId 可选，
  // 缺失时由后端视为新会话生成 id，经 SSE session 事件回传。
  const backendForm = new FormData();
  if (threadId) {
    backendForm.append("threadId", threadId);
  }
  backendForm.append("text", text);
  if (file instanceof File) {
    backendForm.append("file", file, file.name);
  }

  let backendRes: Response;
  try {
    backendRes = await request(`${BACKEND_URL}/api/legal/agent/legalAgent`, {
      method: "POST",
      headers: { Authorization: `Bearer ${auth.token}` },
      body: backendForm,
      timeout: 0, // 流式响应不设超时
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

  // 将后端 SSE 流原样透传给前端
  return new Response(backendRes.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
})
