import { withAuth } from "@/lib/utils/with-auth";
import { forwardNovelStream } from "../../stream";

/**
 * 新建小说弹窗的开场白：交给后端那个独立的开书图，散文逐字流回来，停在提问上。
 *
 * 书 id 由弹窗打开时就生成好，与写章那条路共用一个 id，但两边各跑各的图。
 */
export const POST = withAuth(async (auth, req) => {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "请求格式错误" }, { status: 400 });
  }

  const novelId = String(form.get("novelId") ?? "").trim();
  const text = String(form.get("text") ?? "").trim();

  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });
  if (!text) return Response.json({ error: "至少说一句想写什么" }, { status: 400 });

  return forwardNovelStream(auth, "/api/novel/setup/run", { novelId, text });
});
