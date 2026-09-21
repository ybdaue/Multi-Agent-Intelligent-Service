import { request, RequestError } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

/**
 * 小说侧只读查询的转发口：GET /api/novel/method/<path> → 后端同名口子。
 *
 * 一个文件顶掉十几个转发路由：这些口子形状一模一样（GET + 转发 Authorization），逐个建文件
 * 只是把同一段代码抄十几遍。路径用白名单卡死，别让这个代理变成通往任意后端路径的通道。
 */
const ALLOWED = new Set([
  "novels",
  "chapter/content",
  "chapter/ledger",
  "impacts",
  "outlines",
  "characters",
  "world-rules",
  "timelines",
  "factions",
  "chronicles",
  "items",
  "relations",
  "inspirations",
]);

export const GET = withAuth(async (auth, req) => {
  const path = req.nextUrl.pathname.replace(/^.*\/api\/novel\/method\//, "").replace(/\/+$/, "");
  if (!ALLOWED.has(path)) {
    return Response.json({ error: "未知的查询口" }, { status: 404 });
  }

  try {
    const backendRes = await request(
      `${BACKEND_URL}/api/novel/method/${path}${req.nextUrl.search}`,
      { headers: { Authorization: `Bearer ${auth.token}` } },
    );

    if (!backendRes.ok) {
      const detail = await backendRes.text().catch(() => "");
      return Response.json(
        { error: `Backend error: ${backendRes.status} ${backendRes.statusText}`, detail },
        { status: backendRes.status },
      );
    }

    return Response.json(await backendRes.json());
  } catch (err) {
    const message =
      err instanceof RequestError && err.timeout ? "后端响应超时" : "服务暂时不可用";
    return Response.json({ error: message }, { status: 503 });
  }
});
