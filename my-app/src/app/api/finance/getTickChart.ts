import { requestJSON } from "@/lib/fetch";

/* ── Types ── */

interface TickPoint {
  time: string;
  price: number;
  volume: number;
  avg_price?: number;
}

interface TickChartResponse {
  symbol: string;
  date: string;
  ticks: TickPoint[];
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function getTickChart(symbol: string): Promise<TickChartResponse> {
  return requestJSON(
    `${API_BASE}/api/finance/method/tick?symbol=${encodeURIComponent(symbol)}`,
    { timeout: 15000 },
  );
}
