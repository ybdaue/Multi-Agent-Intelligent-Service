import { NextRequest } from "next/server";
import { headers } from "next/headers";
import { auth } from "@/lib/auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function hashUserId(id: string): number {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return hash;
}

export async function GET(req: NextRequest) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session?.user?.id) {
    return Response.json({ error: "未登录或登录已过期，请重新登录" }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const filename = searchParams.get("filename");
  if (!filename) {
    return Response.json({ error: "缺少文件名" }, { status: 400 });
  }

  const userId = hashUserId(session.user.id);

  let backendRes: Response;
  try {
    backendRes = await fetch(
      `${BACKEND_URL}/download/${userId}/${encodeURIComponent(filename)}`,
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
        backendRes.headers.get("Content-Disposition") ??
        `attachment; filename="${encodeURIComponent(filename)}"`,
    },
  });
}
