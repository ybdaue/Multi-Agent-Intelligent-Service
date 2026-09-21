import { withAuth } from "@/lib/utils/with-auth";
import { forwardNovelStream } from "../../stream";

/** 一句话交给小说图：正文流式回，停在审稿确认上就把问题交回。 */
export const POST = withAuth(async (auth, req) => {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }

  const novelId = String(form.get("novelId") ?? "").trim();
  const text = String(form.get("text") ?? "").trim();
  const chapterId = String(form.get("chapterId") ?? "").trim();

  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });
  if (!text) return Response.json({ error: "至少说一句要写什么" }, { status: 400 });

  return forwardNovelStream(auth, "/api/novel/agent/run", { novelId, text, chapterId });
});
