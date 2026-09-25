import { request, RequestError } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

const BACKEND_PATH = `${BACKEND_URL}/api/novel/method/chapter`;

/** 后端给的那句话（"章节不存在"这类）比"请求失败 (404)"对用户有用 */
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

/** 改章名。只动标题，正文与台账一概不碰。 */
export const PATCH = withAuth(async (auth, req) => {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }

  const novelId = String(form.get("novelId") ?? "").trim();
  const chapterId = String(form.get("chapterId") ?? "").trim();
  const title = String(form.get("title") ?? "").trim();
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });
  if (!chapterId) return Response.json({ error: "缺少章节 id" }, { status: 400 });
  if (!title) return Response.json({ error: "章节标题不能为空" }, { status: 400 });

  const backendForm = new FormData();
  backendForm.append("novelId", novelId);
  backendForm.append("chapterId", chapterId);
  backendForm.append("title", title);

  try {
    const backendRes = await request(BACKEND_PATH, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${auth.token}` },
      body: backendForm,
    });
    if (!backendRes.ok) return forwardError(backendRes, "章名没能改掉");
    return Response.json(await backendRes.json());
  } catch (err) {
    return unavailable(err);
  }
});

/** 删一章。台账靠库里外键级联一并删掉，后端顺带把全书总字数减回来。 */
export const DELETE = withAuth(async (auth, req) => {
  const novelId = req.nextUrl.searchParams.get("novelId")?.trim() ?? "";
  const chapterId = req.nextUrl.searchParams.get("chapterId")?.trim() ?? "";
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });
  if (!chapterId) return Response.json({ error: "缺少章节 id" }, { status: 400 });

  try {
    const backendRes = await request(
      `${BACKEND_PATH}?novelId=${encodeURIComponent(novelId)}&chapterId=${encodeURIComponent(chapterId)}`,
      { method: "DELETE", headers: { Authorization: `Bearer ${auth.token}` } },
    );
    if (!backendRes.ok) return forwardError(backendRes, "章节没能删掉");
    return Response.json(await backendRes.json());
  } catch (err) {
    return unavailable(err);
  }
});
