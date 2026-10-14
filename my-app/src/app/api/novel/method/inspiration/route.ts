import { request, RequestError } from "@/lib/fetch";
import { withAuth, type AuthContext } from "@/lib/utils/with-auth";
import type { NextRequest } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

/** 后端给的那句话（"未知的灵感类型"这类）比"请求失败 (400)"对用户有用 */
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
 * 灵感库的写口：新增 / 改类型（都是 multipart）。字段由前端拼好，这里只做非空校验再原样转发。
 *
 * 另开一个目录而不是塞进 [...path]（那边只转 GET），写口逐个建文件（同 impact/status）。
 * 路径用单数 /inspiration，避开 [...path] 里已有的 GET /inspirations。
 */
async function forwardMultipart(
  auth: AuthContext,
  req: NextRequest,
  method: "POST" | "PATCH",
  fallback: string,
) {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }

  const novelId = String(form.get("novelId") ?? "").trim();
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });

  // 原样重拼一份：文件本体也一起转过去，后端 parse_items 才读得到内容。
  const backendForm = new FormData();
  for (const [key, value] of form.entries()) {
    if (typeof value === "string") backendForm.append(key, value);
    else backendForm.append(key, value, value.name);
  }

  try {
    const backendRes = await request(`${BACKEND_URL}/api/novel/method/inspiration`, {
      method,
      headers: { Authorization: `Bearer ${auth.token}` },
      body: backendForm,
      // 新增要等模型翻译完才回，默认 10s 会被掐断（报"后端响应超时"）；这里不设上限，
      // 后端模型侧自己有 60s 超时兜底。
      timeout: 0,
      // 客户端关窗 abort 时 req.signal 触发，顺手把这趟到后端的请求也断掉
      signal: req.signal,
    });
    if (!backendRes.ok) return forwardError(backendRes, fallback);
    return Response.json(await backendRes.json());
  } catch (err) {
    return unavailable(err);
  }
}

/** 新增一批灵感（文件/链接/文本 + 内容类型） */
export const POST = withAuth((auth, req) => forwardMultipart(auth, req, "POST", "没能添加灵感"));

/** 改一条灵感的内容类型 */
export const PATCH = withAuth((auth, req) => forwardMultipart(auth, req, "PATCH", "没能改掉灵感"));

/** 删一条灵感，或一份素材产出的多条（同一 sourceId 一起删） */
export const DELETE = withAuth(async (auth, req) => {
  const novelId = req.nextUrl.searchParams.get("novelId")?.trim() ?? "";
  const ids = req.nextUrl.searchParams
    .getAll("inspirationId")
    .map((v) => v.trim())
    .filter(Boolean);
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });
  if (ids.length === 0) return Response.json({ error: "缺少灵感 id" }, { status: 400 });

  const qs = new URLSearchParams({ novelId });
  for (const id of ids) qs.append("inspirationId", id);

  try {
    const backendRes = await request(`${BACKEND_URL}/api/novel/method/inspiration?${qs}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${auth.token}` },
    });
    if (!backendRes.ok) return forwardError(backendRes, "没能删除灵感");
    return Response.json(await backendRes.json());
  } catch (err) {
    return unavailable(err);
  }
});