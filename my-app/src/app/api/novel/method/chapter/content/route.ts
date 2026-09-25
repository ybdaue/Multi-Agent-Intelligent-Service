import { request, RequestError } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

const BACKEND_PATH = `${BACKEND_URL}/api/novel/method/chapter/content`;

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

/**
 * 取一章正文的转发口。
 *
 * 这个 GET 原本由 [...path] 那个 catch-all 顶着 —— 但静态段优先于 [...path]，本文件一建出来
 * 就把它遮住了，所以这里必须自己转一遍，同时把 "chapter/content" 从那边的白名单里删掉，
 * 保证一个路径只有一个处理器。漏了会静默 404，正文标签页整片空白。
 */
export const GET = withAuth(async (auth, req) => {
  try {
    const backendRes = await request(`${BACKEND_PATH}${req.nextUrl.search}`, {
      headers: { Authorization: `Bearer ${auth.token}` },
    });
    if (!backendRes.ok) return forwardError(backendRes, "正文没能取回来");
    return Response.json(await backendRes.json());
  } catch (err) {
    return unavailable(err);
  }
});

/**
 * 手改正文落库（防抖后调用）。后端顺带重算这一章与全书字数。
 *
 * 后端的两种冲突分开报：AI 正在写同一章是 409，version 对不上（这一章在别处被改过）是 412。
 * 两句话都得说给用户听，而且出路不一样 —— 所以状态码与 detail 都原样透传，前端照状态码分流。
 *
 * version 是后端给的不透明版本令牌（novel_chapter.updatedAt），只在这里转个名字叫
 * clientUpdatedAt；原样搬运，别解析、别格式化。
 */
export const POST = withAuth(async (auth, req) => {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }

  const novelId = String(form.get("novelId") ?? "").trim();
  const chapterId = String(form.get("chapterId") ?? "").trim();
  const content = String(form.get("content") ?? "");
  const version = String(form.get("version") ?? "").trim();
  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });
  if (!chapterId) return Response.json({ error: "缺少章节 id" }, { status: 400 });
  if (!version) return Response.json({ error: "缺少章节版本" }, { status: 400 });

  const backendForm = new FormData();
  backendForm.append("novelId", novelId);
  backendForm.append("chapterId", chapterId);
  backendForm.append("content", content);
  backendForm.append("clientUpdatedAt", version);

  try {
    const backendRes = await request(BACKEND_PATH, {
      method: "POST",
      headers: { Authorization: `Bearer ${auth.token}` },
      body: backendForm,
    });
    if (!backendRes.ok) return forwardError(backendRes, "正文没能保存");
    return Response.json(await backendRes.json());
  } catch (err) {
    return unavailable(err);
  }
});
