"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { App, DatePicker, Select } from "antd";
import { getOverview, getRecords, getRecharges, getActiveUserPlans, getPaymentOrders, toggleAutoRenew } from "@/lib/server/billing-actions";
import styles from "./page.module.scss";

/* ── 类型 ─────────────────────────────────────────── */

interface Overview {
  balance: number;
  totalCostThisMonth: number;
}

interface BillingRecord {
  id: string;
  serviceType: string;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  totalCost: number;
  balanceAfter: number;
  requestPath: string | null;
  createdAt: Date;
}

interface RechargeRecord {
  id: string;
  amount: number;
  balanceBefore: number;
  balanceAfter: number;
  note: string | null;
  createdAt: Date;
}

interface ActivePlan {
  id: string;
  planId: string;
  totalTokens: number;
  usedTokens: number;
  remainingTokens: number;
  status: string;
  expiresAt: Date | null;
  currentPeriodStart: Date | null;
  currentPeriodEnd: Date | null;
  autoRenew: boolean | null;
  plan: { name: string; type: string; serviceType: string | null; modelName: string | null; isActive: boolean | null };
}

interface PaymentOrder {
  id: string;
  planId: string | null;
  amount: number;
  status: string;
  paymentMethod: string;
  tradeNo: string | null;
  paidAt: Date | null;
  note: string | null;
  expiresAt: Date;
  createdAt: Date;
}

/* ── 工具 ─────────────────────────────────────────── */

function formatCost(cents: number): string {
  return (cents / 100).toFixed(2);
}

function formatDateTime(d: Date): string {
  return d.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function serviceLabel(s: string): string {
  const map: Record<string, string> = {
    novel: "小说",
    legal: "法律",
    finance: "金融",
    chat: "闲聊",
  };
  return map[s] ?? s;
}

function paymentMethodLabel(m: string): string {
  const map: Record<string, string> = {
    balance: "余额支付",
    alipay: "支付宝",
    wxpay: "微信支付",
  };
  return map[m] ?? m;
}

/* ── 主页面 ────────────────────────────────────────── */

export default function BillingPage() {
  const router = useRouter();
  const { modal } = App.useApp();
  // 概览
  const [overview, setOverview] = useState<Overview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);

  // 账单
  const [records, setRecords] = useState<BillingRecord[]>([]);
  const [recordsTotal, setRecordsTotal] = useState(0);
  const [recordsPage, setRecordsPage] = useState(1);
  const [recordsLoading, setRecordsLoading] = useState(true);
  const [recordsError, setRecordsError] = useState<string | null>(null);
  const pageSize = 15;

  // 充值记录
  const [recharges, setRecharges] = useState<RechargeRecord[]>([]);
  const [rechargesTotal, setRechargesTotal] = useState(0);
  const [rechargesPage, setRechargesPage] = useState(1);
  const [rechargesLoading, setRechargesLoading] = useState(true);

  // 活跃套餐
  const [activePlans, setActivePlans] = useState<ActivePlan[]>([]);
  const [activePlansLoading, setActivePlansLoading] = useState(true);

  // 支付订单
  const [orders, setOrders] = useState<PaymentOrder[]>([]);
  const [ordersTotal, setOrdersTotal] = useState(0);
  const [ordersPage, setOrdersPage] = useState(1);
  const [ordersLoading, setOrdersLoading] = useState(true);

  // ── 筛选状态 ──
  // 账单
  const [recordsDateRange, setRecordsDateRange] = useState<[string, string]>(["", ""]);
  const [recordsServiceType, setRecordsServiceType] = useState<string>("");
  // 余额
  const [rechargesDateRange, setRechargesDateRange] = useState<[string, string]>(["", ""]);
  // 订单
  const [ordersDateRange, setOrdersDateRange] = useState<[string, string]>(["", ""]);
  const [ordersPaymentMethod, setOrdersPaymentMethod] = useState<string>("");
  const [ordersStatus, setOrdersStatus] = useState<string>("");

  const [togglingId, setTogglingId] = useState<string | null>(null);

  /* ── 数据获取 ──────────────────────────────────── */

  useEffect(() => {
    getOverview()
      .then((d) => { setOverview(d); setOverviewLoading(false); })
      .catch(() => setOverviewLoading(false));
    getActiveUserPlans()
      .then((d) => { setActivePlans(d); setActivePlansLoading(false); })
      .catch(() => setActivePlansLoading(false));
  }, []);

  const recordsFilters = useMemo(() => ({
    dateFrom: recordsDateRange[0] || undefined,
    dateTo: recordsDateRange[1] || undefined,
    serviceType: recordsServiceType || undefined,
  }), [recordsDateRange, recordsServiceType]);

  const fetchRecords = useCallback(() => {
    setRecordsLoading(true);
    setRecordsError(null);
    getRecords(recordsPage, pageSize, recordsFilters)
      .then((d) => {
        setRecords(d.records ?? []);
        setRecordsTotal(d.total ?? 0);
        setRecordsLoading(false);
      })
      .catch((err: Error) => {
        setRecordsError(err.message);
        setRecordsLoading(false);
      });
  }, [recordsPage, recordsFilters]);

  useEffect(() => { fetchRecords(); }, [fetchRecords]);

  const rechargesFilters = useMemo(() => ({
    dateFrom: rechargesDateRange[0] || undefined,
    dateTo: rechargesDateRange[1] || undefined,
  }), [rechargesDateRange]);

  const fetchRecharges = useCallback(() => {
    setRechargesLoading(true);
    getRecharges(rechargesPage, pageSize, rechargesFilters)
      .then((d) => {
        setRecharges(d.recharges ?? []);
        setRechargesTotal(d.total ?? 0);
        setRechargesLoading(false);
      })
      .catch(() => setRechargesLoading(false));
  }, [rechargesPage, rechargesFilters]);

  useEffect(() => { fetchRecharges(); }, [fetchRecharges]);

  const ordersFilters = useMemo(() => ({
    dateFrom: ordersDateRange[0] || undefined,
    dateTo: ordersDateRange[1] || undefined,
    paymentMethod: ordersPaymentMethod || undefined,
    status: ordersStatus || undefined,
  }), [ordersDateRange, ordersPaymentMethod, ordersStatus]);

  const fetchOrders = useCallback(() => {
    setOrdersLoading(true);
    getPaymentOrders(ordersPage, pageSize, ordersFilters)
      .then((d) => {
        setOrders(d.orders ?? []);
        setOrdersTotal(d.total ?? 0);
        setOrdersLoading(false);
      })
      .catch(() => setOrdersLoading(false));
  }, [ordersPage, ordersFilters]);

  useEffect(() => { fetchOrders(); }, [fetchOrders]);

  const statusMap: Record<string, { label: string; color: string }> = {
    pending: { label: "待付款", color: "#faad14" },
    success: { label: "已付款", color: "#52c41a" },
    failed: { label: "失败", color: "#ff4d4f" },
    expired: { label: "已过期", color: "var(--color-text-tertiary)" },
    cancelled: { label: "已取消", color: "var(--color-text-tertiary)" },
  };

  const handleToggleAutoRenew = (userPlanId: string, current: boolean) => {
    modal.confirm({
      title: current ? "关闭自动续费" : "开启自动续费",
      content: current ? "关闭后，当前周期结束后将不再自动续费。" : "开启后，当前周期结束后将自动从余额扣款续费。",
      okText: "确定",
      cancelText: "取消",
      onOk: async () => {
        setTogglingId(userPlanId);
        try {
          await toggleAutoRenew(userPlanId, !current);
          setActivePlans((prev) =>
            prev.map((p) => (p.id === userPlanId ? { ...p, autoRenew: !current } : p)),
          );
        } catch (e: unknown) {
          console.error(e);
        } finally { setTogglingId(null); }
      },
    });
  };

  const totalPages = Math.ceil(recordsTotal / pageSize);

  return (
    <div className={styles.page}>
      {/* ── 余额概览卡片 ── */}
      <div className={styles.overviewCards}>
        <div className={styles.card}>
          <div className={styles.cardLabel}>账户余额</div>
          <div className={styles.cardValue}>
            {overviewLoading ? "..." : `¥${formatCost(overview?.balance ?? 0)}`}
          </div>
        </div>
        <div className={styles.card}>
          <div className={styles.cardLabel}>本月消费</div>
          <div className={styles.cardValue}>
            {overviewLoading
              ? "..."
              : `¥${formatCost(overview?.totalCostThisMonth ?? 0)}`}
          </div>
        </div>
      </div>

      {/* ── 活跃套餐 ── */}
      {!activePlansLoading && activePlans.length > 0 && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>
            活跃套餐
            <span
              style={{
                float: "right", fontSize: 13, fontWeight: 400, cursor: "pointer", color: "var(--color-primary)",
              }}
              onClick={() => router.push("/billing/plans")}
            >
              套餐中心 →
            </span>
          </h2>
          <div style={{ padding: "0.75rem 1.25rem" }}>
            {activePlans.map((up) => {
              const isRecharge = up.totalTokens === 0;
              const usedPct = isRecharge ? 0 : Math.min(100, Math.round((up.usedTokens / up.totalTokens) * 100));
              return (
                <div key={up.id} style={{
                  display: "flex", alignItems: "center", gap: 12, padding: "0.5rem 0",
                  borderBottom: "1px solid var(--color-border)",
                }}>
                  <div style={{ flex: 1, fontSize: "0.875rem", fontWeight: 500 }}>{up.plan.name}</div>
                  {isRecharge ? (
                    <span style={{ fontSize: "0.8125rem", color: "#52c41a", fontWeight: 500 }}>已生效</span>
                  ) : (
                    <>
                      <div style={{ fontSize: "0.8125rem", color: "var(--color-text-secondary)", textAlign: "right" }}>
                        <div>{up.remainingTokens.toLocaleString()} / {up.totalTokens.toLocaleString()} tokens</div>
                        <div style={{ fontSize: "0.75rem", marginTop: 2 }}>
                          {up.expiresAt
                            ? `有效期至 ${new Date(up.expiresAt).toLocaleDateString("zh-CN")}`
                            : up.currentPeriodEnd
                              ? `周期至 ${new Date(up.currentPeriodEnd).toLocaleDateString("zh-CN")}`
                              : ""}
                        </div>
                      </div>
                      <div style={{ width: 100, height: 6, background: "var(--color-border)", borderRadius: 3, overflow: "hidden" }}>
                        <div style={{
                          height: "100%", background: "var(--color-primary)", borderRadius: 3,
                          width: `${usedPct}%`, transition: "width 0.3s",
                        }} />
                      </div>
                      <span style={{ fontSize: 12, color: "var(--color-text-tertiary)", minWidth: 30 }}>{usedPct}%</span>
                      {up.plan.type === "subscription" && up.plan.isActive && (
                        <button
                          onClick={() => handleToggleAutoRenew(up.id, !!up.autoRenew)}
                          disabled={togglingId === up.id}
                          style={{
                            fontSize: "0.75rem", padding: "3px 8px", borderRadius: 4,
                            border: "1px solid",
                            borderColor: up.autoRenew ? "#ff7875" : "#52c41a",
                            background: "var(--color-surface)",
                            color: up.autoRenew ? "#ff4d4f" : "#52c41a",
                            cursor: "pointer", whiteSpace: "nowrap",
                          }}
                        >
                          {togglingId === up.id ? "..." : up.autoRenew ? "关闭续费" : "开启续费"}
                        </button>
                      )}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── 去套餐中心 ── */}
      {!activePlansLoading && activePlans.length === 0 && (
        <div style={{
          textAlign: "center", padding: "1rem", marginBottom: "1rem",
          background: "var(--color-surface)", border: "1px dashed var(--color-border)",
          borderRadius: "var(--radius-md)", fontSize: "0.875rem", color: "var(--color-text-secondary)",
        }}>
          还没有活跃套餐，
          <span style={{ color: "var(--color-primary)", cursor: "pointer" }} onClick={() => router.push("/billing/plans")}>
            去套餐中心购买 →
          </span>
        </div>
      )}

      {/* ── 账单明细 ── */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>
          账单明细
          <span className={styles.filterBar}>
            <DatePicker.RangePicker
              size="small"
              onChange={(_, ds) => { setRecordsDateRange(ds ? (ds as [string, string]) : ["", ""]); setRecordsPage(1); }}
            />
            <Select
              size="small"
              allowClear
              placeholder="服务"
              style={{ width: 100 }}
              value={recordsServiceType || undefined}
              onChange={(v) => { setRecordsServiceType(v ?? ""); setRecordsPage(1); }}
              options={[
                { value: "novel", label: "小说" },
                { value: "legal", label: "法律" },
                { value: "finance", label: "金融" },
                { value: "chat", label: "闲聊" },
              ]}
            />
          </span>
        </h2>
        {recordsError ? (
          <div className={styles.emptyState}>{recordsError}</div>
        ) : recordsLoading ? (
          <div className={styles.skeleton}>
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className={styles.skeletonRow} />
            ))}
          </div>
        ) : records.length === 0 ? (
          <div className={styles.emptyState}>暂无账单记录</div>
        ) : (
          <>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>服务</th>
                  <th className={styles.num}>Input</th>
                  <th className={styles.num}>Output</th>
                  <th className={styles.num}>费用</th>
                  <th className={styles.num}>余额</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => (
                  <tr key={r.id}>
                    <td className={styles.timeCol}>
                      {formatDateTime(r.createdAt)}
                    </td>
                    <td>{serviceLabel(r.serviceType)}</td>
                    <td className={styles.num}>
                      {r.inputTokens.toLocaleString()}
                    </td>
                    <td className={styles.num}>
                      {r.outputTokens.toLocaleString()}
                    </td>
                    <td className={styles.num}>
                      ¥{formatCost(r.totalCost)}
                    </td>
                    <td className={styles.num}>
                      ¥{formatCost(r.balanceAfter)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* 分页 */}
            <div className={styles.pagination}>
              <span>
                第 {recordsPage} / {totalPages || 1} 页（共 {recordsTotal} 条）
              </span>
              <div className={styles.paginationButtons}>
                <button
                  disabled={recordsPage <= 1}
                  onClick={() => setRecordsPage((p) => p - 1)}
                >
                  上一页
                </button>
                <button
                  disabled={recordsPage >= totalPages}
                  onClick={() => setRecordsPage((p) => p + 1)}
                >
                  下一页
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* ── 余额记录 ── */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>
          余额记录
          <span className={styles.filterBar}>
            <DatePicker.RangePicker
              size="small"
              onChange={(_, ds) => { setRechargesDateRange(ds ? (ds as [string, string]) : ["", ""]); setRechargesPage(1); }}
            />
          </span>
        </h2>
        {rechargesLoading ? (
          <div className={styles.skeleton}>
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className={styles.skeletonRow} />
            ))}
          </div>
        ) : recharges.length === 0 ? (
          <div className={styles.emptyState}>暂无余额记录</div>
        ) : (
          <>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>时间</th>
                  <th className={styles.num}>变动金额</th>
                  <th className={styles.num}>变动前</th>
                  <th className={styles.num}>变动后</th>
                  <th>备注</th>
                </tr>
              </thead>
              <tbody>
                {recharges.map((r) => (
                  <tr key={r.id}>
                    <td className={styles.timeCol}>
                      {formatDateTime(r.createdAt)}
                    </td>
                    <td className={styles.num}>
                      {formatCost(r.amount)}¥
                    </td>
                    <td className={styles.num}>
                      {formatCost(r.balanceBefore)}¥
                    </td>
                    <td className={styles.num}>
                      {formatCost(r.balanceAfter)}¥
                    </td>
                    <td>{r.note ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className={styles.pagination}>
              <span>
                第 {rechargesPage} /{" "}
                {Math.ceil(rechargesTotal / pageSize) || 1} 页（共{" "}
                {rechargesTotal} 条）
              </span>
              <div className={styles.paginationButtons}>
                <button
                  disabled={rechargesPage <= 1}
                  onClick={() => setRechargesPage((p) => p - 1)}
                >
                  上一页
                </button>
                <button
                  disabled={
                    rechargesPage >= Math.ceil(rechargesTotal / pageSize)
                  }
                  onClick={() => setRechargesPage((p) => p + 1)}
                >
                  下一页
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* ── 订单记录 ── */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>
          订单记录
          <span className={styles.filterBar}>
            <DatePicker.RangePicker
              size="small"
              onChange={(_, ds) => { setOrdersDateRange(ds ? (ds as [string, string]) : ["", ""]); setOrdersPage(1); }}
            />
            <Select
              size="small"
              allowClear
              placeholder="支付方式"
              style={{ width: 110 }}
              value={ordersPaymentMethod || undefined}
              onChange={(v) => { setOrdersPaymentMethod(v ?? ""); setOrdersPage(1); }}
              options={[
                { value: "balance", label: "余额支付" },
                { value: "alipay", label: "支付宝" },
                { value: "wxpay", label: "微信支付" },
              ]}
            />
            <Select
              size="small"
              allowClear
              placeholder="状态"
              style={{ width: 100 }}
              value={ordersStatus || undefined}
              onChange={(v) => { setOrdersStatus(v ?? ""); setOrdersPage(1); }}
              options={[
                { value: "pending", label: "待付款" },
                { value: "success", label: "已付款" },
                { value: "failed", label: "失败" },
                { value: "expired", label: "已过期" },
                { value: "cancelled", label: "已取消" },
              ]}
            />
          </span>
        </h2>
        {ordersLoading ? (
          <div className={styles.skeleton}>
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className={styles.skeletonRow} />
            ))}
          </div>
        ) : orders.length === 0 ? (
          <div className={styles.emptyState}>暂无订单记录</div>
        ) : (
          <>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>套餐</th>
                  <th className={styles.num}>金额</th>
                  <th>支付方式</th>
                  <th>状态</th>
                  <th>交易号</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => {
                  const st = statusMap[o.status] ?? { label: o.status, color: "var(--color-text-tertiary)" };
                  return (
                    <tr key={o.id}>
                      <td className={styles.timeCol}>
                        {formatDateTime(o.createdAt)}
                      </td>
                      <td>{o.note ?? "-"}</td>
                      <td className={styles.num}>¥{formatCost(o.amount)}</td>
                      <td>{paymentMethodLabel(o.paymentMethod)}</td>
                      <td>
                        <span style={{
                          color: st.color, fontSize: "0.8125rem",
                          fontWeight: 500,
                        }}>{st.label}</span>
                      </td>
                      <td style={{ fontSize: "0.75rem", color: "var(--color-text-secondary)" }}>
                        {o.tradeNo ?? "-"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            <div className={styles.pagination}>
              <span>
                第 {ordersPage} /{" "}
                {Math.ceil(ordersTotal / pageSize) || 1} 页（共{" "}
                {ordersTotal} 条）
              </span>
              <div className={styles.paginationButtons}>
                <button
                  disabled={ordersPage <= 1}
                  onClick={() => setOrdersPage((p) => p - 1)}
                >
                  上一页
                </button>
                <button
                  disabled={ordersPage >= Math.ceil(ordersTotal / pageSize)}
                  onClick={() => setOrdersPage((p) => p + 1)}
                >
                  下一页
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}