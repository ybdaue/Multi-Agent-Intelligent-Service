import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

function hashUserId(id: string): number {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return hash;
}

export const GET = withAuth(async (auth, req) => {
  const { searchParams } = new URL(req.url);
  const fileId = searchParams.get("fileId");
  if (!fileId) {
    return Response.json({ error: "缺少文件 ID" }, { status: 400 });
  }

  const userId = hashUserId(auth.userId);

  let backendRes: Response;
  try {
    backendRes = await fetch(
      `${BACKEND_URL}/api/legal/method/download/${userId}/${encodeURIComponent(fileId)}`,
      { headers: { Authorization: `Bearer ${auth.token}` } },
    );
  } catch {
    return Response.json({ error: "后端下载服务不可用" }, { status: 502 });
  }

  if (!backendRes.ok) {
    return Response.json(
      { error: `下载失败 (${backendRes.status})` },
      { status: backendRes.status },
    );
  }

  return new Response(backendRes.body, {
    headers: {
      "Content-Type":
        backendRes.headers.get("Content-Type") ??
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "Content-Disposition":
        backendRes.headers.get("Content-Disposition") ?? "attachment",
    },
  });
});
