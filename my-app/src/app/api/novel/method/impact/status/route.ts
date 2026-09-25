import { request, RequestError } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

/** 后端给的那句话（"受影响点不存在"这类）比"请求失败 (404)"对用户有用 */
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

/**
 * 把一处受影响点标成已处理（接受 / 跳过 / 已修）。
 *
 * 另开一个目录而不是塞进 [...path] 那个口子：那边只转 GET，写口逐个建文件（同 chapter/status）。
 * 四档取值由后端再挡一道（api/novel/method.py 的 IMPACT_STATUSES），这里只做非空校验。
 * resolution 是可选的"怎么处理的"，面板上暂时不发，带上就一并转给后端。
 */
export const POST = withAuth(async (auth, req) => {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }

  const novelId = String(form.get("novelId") ?? "").trim();
  const impactId = String(form.get("impactId") ?? "").trim();
  const status = String(form.get("status") ?? "").trim();
  const resolution = String(form.get("resolution") ?? "").trim();
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });
  if (!impactId) return Response.json({ error: "缺少受影响点 id" }, { status: 400 });
  if (!status) return Response.json({ error: "缺少处理状态" }, { status: 400 });

  const backendForm = new FormData();
  backendForm.append("novelId", novelId);
  backendForm.append("impactId", impactId);
  backendForm.append("status", status);
  if (resolution) backendForm.append("resolution", resolution);

  try {
    const backendRes = await request(`${BACKEND_URL}/api/novel/method/impact/status`, {
      method: "POST",
      headers: { Authorization: `Bearer ${auth.token}` },
      body: backendForm,
    });
    if (!backendRes.ok) return forwardError(backendRes, "受影响点没能改掉");
    return Response.json(await backendRes.json());
  } catch (err) {
    return Response.json(
      { error: err instanceof RequestError && err.timeout ? "后端响应超时" : "服务暂时不可用" },
      { status: 503 },
    );
  }
});
