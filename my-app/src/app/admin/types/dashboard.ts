export type TimeRange = "total" | "year" | "month";

export interface TimeContext {
  range: TimeRange;
  year: number;
  month: number;
}

export interface DashboardSummary {
  userCount: number;
  novelCount: number;
  totalChapters: number;
  totalRevenue: number;
  totalRecharge: number;
  totalBillingRecords: number;
  planSoldCount: number;
  paidUserCount: number;
  pendingOrderCount: number;
  realRevenue: number;
  bonusAmount: number;
  adminRecharge: number;
  adminDeduction: number;
  todayNewUsers: number;
  todayRevenue: number;
  todayRecharge: number;
}

export interface TrendItem {
  date: string;
  dau: number;
  loginDau: number;
  newUsers: number;
  revenue: number;
  recharge: number;
  realRevenue: number;
  userRecharge: number;
  adminRecharge: number;
  newNovels: number;
  newChapters: number;
}

export interface ServiceDistribution {
  serviceType: string;
  callCount: number;
  totalCost: number;
  percentage: number;
}

export interface RecentBillingItem {
  id: string;
  userId: string;
  userEmail: string;
  serviceType: string;
  totalCost: number;
  createdAt: string;
}

export interface ModelRankingItem {
  modelName: string;
  serviceType: string;
  callCount: number;
  totalCost: number;
  inputTokens: number;
  outputTokens: number;
}

export interface UserTopItem {
  userId: string;
  userEmail: string;
  userName: string | null;
  billingCount: number;
  totalCost: number;
}

export interface PlanRankingItem {
  planId: string;
  planName: string;
  planType: string;
  price: number;
  soldCount: number;
  totalRevenue: number;
}