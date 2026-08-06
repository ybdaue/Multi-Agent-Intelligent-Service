import { requestJSON } from "@/lib/fetch";

/* ── Types ── */

interface StockData {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  amount: number;
}

interface StockListParams {
  page: number;
  pageSize: number;
  keyword?: string;
  sortBy?: string;
  sortDir?: "asc" | "desc";
}

interface StockListResponse {
  stocks: StockData[];
  total: number;
  page: number;
  page_size: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function getStockList(params: StockListParams = {page: 1,pageSize: 10}): Promise<StockListResponse> {
  const query = new URLSearchParams();
  query.set("page", String(params.page));
  query.set("page_size", String(params.pageSize));
  if (params.keyword) query.set("keyword", params.keyword);
  if (params.sortBy) query.set("sort_by", params.sortBy);
  if (params.sortDir) query.set("sort_dir", params.sortDir);

  return requestJSON(`${API_BASE}/api/finance/method/latest?${query.toString()}`, {
    method: "GET",
    timeout: 60000,
  });
}
