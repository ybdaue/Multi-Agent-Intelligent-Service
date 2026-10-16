import { withAuth } from "@/lib/utils/with-auth";
import { forwardNovelStream } from "../../stream";

/**
 * 人工改稿：用户在正文框里改完点了保存，把这一章改后的正文交给小说图。
 *
 * 后端见 manual_content 就短路意图识别、直接进 editor.manual 比对两稿、重报台账、定严重程度，
 * 再按级派发审稿、走入库确认。它同时也是一道章节状态闸：已定稿 / 生成中的章会被挡回 400，
 * 这里把后端那句话原样转给前端显示。
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

  if (!novelId) return Response.json({ error: "缺少小说 id" }, { status: 400 });
  if (!chapterId) return Response.json({ error: "缺少章节 id" }, { status: 400 });
  if (!content.trim()) return Response.json({ error: "改后的正文不能是空的" }, { status: 400 });

  return forwardNovelStream(auth, "/api/novel/agent/manual", {
    novelId,
    chapterId,
    content,
  });
});