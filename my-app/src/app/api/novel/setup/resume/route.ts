import { withAuth } from "@/lib/utils/with-auth";
import { forwardNovelStream } from "../../stream";

/** 用户答了开书图停下来的那一问（下一项设定 / 整份清单的意见），接着往下跑。 */
export const POST = withAuth(async (auth, req) => {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }

  const novelId = String(form.get("novelId") ?? "").trim();
  const answer = String(form.get("answer") ?? "").trim();

  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });
  if (!answer) return Response.json({ error: "答复不能为空" }, { status: 400 });

  return forwardNovelStream(auth, "/api/novel/setup/resume", { novelId, answer });
});
