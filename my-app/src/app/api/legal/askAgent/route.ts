import { NextRequest } from "next/server";
import { headers } from "next/headers";
import { auth } from "@/lib/auth";
import { request } from "@/lib/fetch";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * 将 better-auth 的 cuid 用户 ID 稳定映射为后端可用的正整数。
 * 后端仅把 userId 作为记忆命名空间与输出目录的隔离 key，非真实数据库主键，
 * 因此使用稳定哈希即可（实际碰撞概率可忽略）。
 */
function hashUserId(id: string): number {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return hash;
}

export async function POST(req: NextRequest) {
  // 1. 用户身份校验：校验通过后才允许转发请求到后端 agent
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session?.user?.id) {
    return Response.json({ error: "未登录或登录已过期，请重新登录" }, { status: 401 });
  }
  const userId = hashUserId(session.user.id);

  // 2. 解析客户端 multipart 表单
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }
  const threadId = String(form.get("threadId") ?? "").trim();
  const text = String(form.get("text") ?? "").trim();
  const file = form.get("file");

  if (!threadId) {
    return Response.json({ error: "缺少会话 ID" }, { status: 400 });
  }
  if (!text) {
    return Response.json({ error: "文本不能为空" }, { status: 400 });
  }

  // 3. 构造后端表单并转发到 /multiAgent
  const backendForm = new FormData();
  backendForm.append("threadId", threadId);
  backendForm.append("text", text);
  if (file instanceof File) {
    backendForm.append("file", file, file.name);
  }

  let backendRes: Response;
  try {
    backendRes = await request(`${BACKEND_URL}/multiAgent?userId=${userId}`, {
      method: "POST",
      body: backendForm,
      timeout: 0, // 流式响应不设超时
    });
  } catch {
    return Response.json({ error: "AI 后端服务不可用" }, { status: 502 });
  }

  if (!backendRes.ok) {
    const detail = await backendRes.text().catch(() => "");
    return Response.json(
      { error: `后端请求失败 (${backendRes.status})`, detail },
      { status: backendRes.status },
    );
  }

  // 4. 将后端 SSE 流原样透传给前端
  return new Response(backendRes.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
