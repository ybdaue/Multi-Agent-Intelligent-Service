import { request, RequestError } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

/** 后端给的那句话（"小说不存在"这类）比"请求失败 (404)"对用户有用 */
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
 * 改书名 / 类型 / 文风。只改传上来的那几项，没传的后端原样留着。
 *
 * 前端改书名也走这里（原来的 POST 还留着，是给没跟上的调用方的一个旧口子）。
 */
export const PATCH = withAuth(async (auth, req) => {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }

  const novelId = String(form.get("novelId") ?? "").trim();
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });

  const backendForm = new FormData();
  backendForm.append("novelId", novelId);
  for (const field of ["title", "tropes", "style"]) {
    const value = form.get(field);
    if (value !== null) backendForm.append(field, String(value));
  }
  if (!["title", "tropes", "style"].some((field) => backendForm.has(field))) {
    return Response.json({ error: "没有要改的内容" }, { status: 400 });
  }

  try {
    const backendRes = await request(`${BACKEND_URL}/api/novel/method/novel`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${auth.token}` },
      body: backendForm,
    });
    if (!backendRes.ok) return forwardError(backendRes, "小说信息没能改掉");
    return Response.json(await backendRes.json());
  } catch (err) {
    return unavailable(err);
  }
});

/** 改书名。只动 title，设定一概不碰。 */
export const POST = withAuth(async (auth, req) => {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }

  const novelId = String(form.get("novelId") ?? "").trim();
  const title = String(form.get("title") ?? "").trim();
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });
  if (!title) return Response.json({ error: "书名不能为空" }, { status: 400 });

  const backendForm = new FormData();
  backendForm.append("novelId", novelId);
  backendForm.append("title", title);

  try {
    const backendRes = await request(`${BACKEND_URL}/api/novel/method/novel`, {
      method: "POST",
      headers: { Authorization: `Bearer ${auth.token}` },
      body: backendForm,
    });
    if (!backendRes.ok) return forwardError(backendRes, "改名失败");
    return Response.json(await backendRes.json());
  } catch (err) {
    return unavailable(err);
  }
});

/** 删书。章节与各类设定靠库里外键级联一并删掉。 */
export const DELETE = withAuth(async (auth, req) => {
  const novelId = req.nextUrl.searchParams.get("novelId")?.trim() ?? "";
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });

  try {
    const backendRes = await request(
      `${BACKEND_URL}/api/novel/method/novel?novelId=${encodeURIComponent(novelId)}`,
      { method: "DELETE", headers: { Authorization: `Bearer ${auth.token}` } },
    );
    if (!backendRes.ok) return forwardError(backendRes, "删除失败");
    return Response.json(await backendRes.json());
  } catch (err) {
    return unavailable(err);
  }
});
