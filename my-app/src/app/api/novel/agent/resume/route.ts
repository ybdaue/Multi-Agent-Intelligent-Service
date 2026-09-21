import { withAuth } from "@/lib/utils/with-auth";
import { forwardNovelStream } from "../../stream";

/** 用户答了图停下来的那个问题（收下这一稿 / 说往哪儿改），接着往下跑。 */
export const POST = withAuth(async (auth, req) => {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }

  const novelId = String(form.get("novelId") ?? "").trim();
  const answer = String(form.get("answer") ?? "").trim();
  const chapterId = String(form.get("chapterId") ?? "").trim();

  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });
  if (!answer) return Response.json({ error: "答复不能为空" }, { status: 400 });

  return forwardNovelStream(auth, "/api/novel/agent/resume", { novelId, answer, chapterId });
});
