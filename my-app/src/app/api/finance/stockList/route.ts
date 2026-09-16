import { request } from "@/lib/fetch";
import { withAuth } from "@/lib/utils/with-auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export const GET = withAuth(async (auth, req) => {
  const { searchParams } = new URL(req.url);

  const query = new URLSearchParams();
  query.set("page", searchParams.get("page") ?? "1");
  query.set("page_size", searchParams.get("pageSize") ?? "10");

  const keyword = searchParams.get("keyword");
  if (keyword) query.set("keyword", keyword);
  const sortBy = searchParams.get("sortBy");
  if (sortBy) query.set("sort_by", sortBy);
  const sortDir = searchParams.get("sortDir");
  if (sortDir) query.set("sort_dir", sortDir);

  const backendRes = await request(
    `${BACKEND_URL}/api/finance/method/latest?${query.toString()}`,
    { headers: { Authorization: `Bearer ${auth.token}` }, timeout: 60000 },
  );

  if (!backendRes.ok) {
    return Response.json(
      { error: `后端请求失败 (${backendRes.status})` },
      { status: backendRes.status },
    );
  }

  return new Response(backendRes.body, {
    headers: {
      "Content-Type":
        backendRes.headers.get("Content-Type") ?? "application/json",
    },
  });
});
