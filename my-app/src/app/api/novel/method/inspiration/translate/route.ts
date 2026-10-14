import { request, RequestError } from "@/lib/fetch";
import { withAuth, type AuthContext } from "@/lib/utils/with-auth";
import type { NextRequest } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

/** 后端给的那句话（"灵感不存在"这类）比"请求失败 (404)"对用户有用 */
async function forwardError(res: Response, fallback: string) {
  const detail = await res.json().catch(() => null);
  const message =
    typeof detail?.error === "string"
      ? detail.error
      : typeof detail?.detail === "string"
        ? detail.detail
        : fallback;
  return Response.json({ error: message }, { status: res.status });
}

function unavailable(err: unknown) {
  return Response.json(
    { error: err instanceof RequestError && err.timeout ? "后端响应超时" : "服务暂时不可用" },
    { status: 503 },
  );
}

/**
 * 重新翻译一份素材：按素材卡上选的标签重跑模型，重建这份素材产出的灵感（缺的补、多的删）。
 *
 * 单开一个目录（同 inspiration/route.ts）：[...path] 只转 GET，写口得逐个建文件。
 */
export const POST = withAuth(async (auth: AuthContext, req: NextRequest) => {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }

  const novelId = String(form.get("novelId") ?? "").trim();
  const ids = form
    .getAll("inspirationId")
    .map((v) => String(v).trim())
    .filter(Boolean);
  const categories = form
    .getAll("category")
    .map((v) => String(v).trim())
    .filter(Boolean);
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });
  if (ids.length === 0) return Response.json({ error: "缺少灵感 id" }, { status: 400 });
  if (categories.length === 0) return Response.json({ error: "至少选一个标签" }, { status: 400 });

  const backendForm = new FormData();
  backendForm.append("novelId", novelId);
  for (const id of ids) backendForm.append("inspirationId", id);
  for (const c of categories) backendForm.append("category", c);

  try {
    const backendRes = await request(`${BACKEND_URL}/api/novel/method/inspiration/translate`, {
      method: "POST",
      headers: { Authorization: `Bearer ${auth.token}` },
      body: backendForm,
      // 重新翻译要等模型出结果，默认 10s 会被掐断；后端模型侧有 60s 超时兜底。
      timeout: 0,
    });
    if (!backendRes.ok) return forwardError(backendRes, "没能重新翻译");
    return Response.json(await backendRes.json());
  } catch (err) {
    return unavailable(err);
  }
});