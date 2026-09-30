import type {
  DashboardSummary,
  TrendItem,
  ServiceDistribution,
  RecentBillingItem,
  ModelRankingItem,
  UserTopItem,
  PlanRankingItem,
  TimeContext,
} from "../../admin/types/dashboard";

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `请求失败 (${res.status})`);
  }
  return res.json();
}

function buildQuery(ctx: TimeContext): string {
  const params = new URLSearchParams({ range: ctx.range });
  if (ctx.range === "year" || ctx.range === "month") {
    params.set("year", String(ctx.year));
  }
  if (ctx.range === "month") {
    params.set("month", String(ctx.month));
  }
  return params.toString();
}

export function fetchSummary(ctx: TimeContext): Promise<DashboardSummary> {
  return fetchJson(`/api/admin/dashboard/summary?${buildQuery(ctx)}`);
}

export function fetchTrends(ctx: TimeContext): Promise<TrendItem[]> {
  if (ctx.range === "total") return Promise.resolve([]);
  return fetchJson(`/api/admin/dashboard/trends?${buildQuery(ctx)}`);
}

export function fetchDistribution(ctx: TimeContext): Promise<ServiceDistribution[]> {
  if (ctx.range === "total") return Promise.resolve([]);
  return fetchJson(`/api/admin/dashboard/distribution?${buildQuery(ctx)}`);
}

export function fetchModelRanking(ctx: TimeContext): Promise<ModelRankingItem[]> {
  return fetchJson(`/api/admin/dashboard/model-ranking?${buildQuery(ctx)}`);
}

export function fetchUserTop(ctx: TimeContext): Promise<UserTopItem[]> {
  return fetchJson(`/api/admin/dashboard/user-top?${buildQuery(ctx)}`);
}

export function fetchPlanRanking(ctx: TimeContext): Promise<PlanRankingItem[]> {
  return fetchJson(`/api/admin/dashboard/plan-ranking?${buildQuery(ctx)}`);
}

export function fetchServiceRanking(ctx: TimeContext): Promise<ServiceDistribution[]> {
  return fetchJson(`/api/admin/dashboard/distribution?${buildQuery(ctx)}`);
}

export function fetchRecentBilling(limit = 10): Promise<RecentBillingItem[]> {
  return fetchJson(`/api/admin/dashboard/recent-billing?limit=${limit}`);
}