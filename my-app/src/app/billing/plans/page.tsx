"use client";

import "@ant-design/v5-patch-for-react-19";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { App, Modal, Radio } from "antd";
import {
  getActivePlans, getUserPlans, getOverview, buyPlan,
  createPaymentOrder, mockPayOrder, toggleAutoRenew,
} from "@/lib/server/billing-actions";
import styles from "./page.module.scss";

type Plan = Awaited<ReturnType<typeof getActivePlans>>[number];
type UserPlan = Awaited<ReturnType<typeof getUserPlans>>[number];

const typeLabels: Record<string, string> = {
  recharge: "充值套餐",
  token: "Token套餐",
  subscription: "订阅套餐",
};

const serviceLabels: Record<string, string> = {
  novel: "小说", legal: "法律", finance: "金融", chat: "闲聊",
};

function formatPrice(cents: number): string {
  return (cents / 100).toFixed(2);
}

export default function PlanStorePage() {
  const router = useRouter();
  const { message: msg, modal } = App.useApp();

  const [plans, setPlans] = useState<Plan[]>([]);
  const [userPlans, setUserPlans] = useState<UserPlan[]>([]);
  const [balance, setBalance] = useState(0);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"buy" | "mine">("buy");

  // 支付弹窗
  const [payModalOpen, setPayModalOpen] = useState(false);
  const [payPlan, setPayPlan] = useState<Plan | null>(null);
  const [payMethod, setPayMethod] = useState<string>("balance");
  const [payProcessing, setPayProcessing] = useState(false);
  const [pendingOrderId, setPendingOrderId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [p, up, ov] = await Promise.all([
        getActivePlans(),
        getUserPlans(),
        getOverview(),
      ]);
      setPlans(p);
      setUserPlans(up);
      setBalance(ov.balance);
    } catch { /* */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleBuy = (plan: Plan) => {
    setPayPlan(plan);
    setPayMethod("balance");
    setPendingOrderId(null);
    setPayModalOpen(true);
  };

  const handleConfirmPay = async () => {
    if (!payPlan) return;
    setPayProcessing(true);
    try {
      if (payMethod === "balance") {
        await buyPlan(payPlan.id);
        msg.success("购买成功！");
        setPayModalOpen(false);
        fetchData();
      } else {
        const order = await createPaymentOrder(payPlan.id, payMethod);
        setPendingOrderId(order.id);
        msg.success("订单已创建，请完成支付");
      }
    } catch (e: unknown) {
      msg.error(e instanceof Error ? e.message : "操作失败");
    } finally { setPayProcessing(false); }
  };

  const handleMockPay = async () => {
    if (!pendingOrderId) return;
    setPayProcessing(true);
    try {
      await mockPayOrder(pendingOrderId);
      msg.success("支付成功！");
      setPayModalOpen(false);
      fetchData();
    } catch (e: unknown) {
      msg.error(e instanceof Error ? e.message : "支付失败");
    } finally { setPayProcessing(false); }
  };

  const handleCancelPay = () => {
    setPayModalOpen(false);
    setPayPlan(null);
    setPendingOrderId(null);
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
          msg.success(current ? "已关闭自动续费" : "已开启自动续费");
          fetchData();
        } catch (e: unknown) {
          msg.error(e instanceof Error ? e.message : "操作失败");
        } finally { setTogglingId(null); }
      },
    });
  };

  const grouped = plans.reduce<Record<string, Plan[]>>((acc, p) => {
    if (!acc[p.type]) acc[p.type] = [];
    acc[p.type].push(p);
    return acc;
  }, {});

  // 已购买的活跃套餐 ID 集合（所有套餐都禁止重复购买）
  const ownedPlanIds = new Set(
    userPlans
      .filter((up) => {
        if (up.status !== "active") return false;
        if (!up.plan?.type) return false;
        // 额度用完或已过期的套餐不阻塞重新购买
        if (up.remainingTokens <= 0 && up.totalTokens > 0) return false;
        if (up.expiresAt && new Date(up.expiresAt) < new Date()) return false;
        if (up.currentPeriodEnd && new Date(up.currentPeriodEnd) < new Date()) return false;
        return true;
      })
      .map((up) => up.planId),
  );

  /** 判断某个套餐是否已被当前用户拥有 */
  const isOwned = (plan: Plan) => ownedPlanIds.has(plan.id);

  const formatToken = (n: number | null) => {
    if (!n) return "-";
    return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : `${(n / 1000).toFixed(0)}K`;
  };

  if (loading) {
    return <div className={styles.page}><p style={{ textAlign: "center", paddingTop: 80, color: "var(--color-text-tertiary)" }}>加载中...</p></div>;
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>套餐中心</h1>
        <span className={styles.backLink} onClick={() => router.push("/billing")}>
          ← 返回账单
        </span>
      </div>

      {/* Tab 切换 */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <button
          onClick={() => setActiveTab("buy")}
          style={{
            padding: "6px 16px", borderRadius: 6, border: "1px solid var(--color-border)",
            background: activeTab === "buy" ? "var(--color-primary)" : "var(--color-surface)",
            color: activeTab === "buy" ? "#fff" : "var(--color-text)",
            cursor: "pointer", fontSize: 14, fontWeight: 500,
          }}
        >
          购买套餐
        </button>
        <button
          onClick={() => setActiveTab("mine")}
          style={{
            padding: "6px 16px", borderRadius: 6, border: "1px solid var(--color-border)",
            background: activeTab === "mine" ? "var(--color-primary)" : "var(--color-surface)",
            color: activeTab === "mine" ? "#fff" : "var(--color-text)",
            cursor: "pointer", fontSize: 14, fontWeight: 500,
          }}
        >
          我的套餐
        </button>
      </div>

      <div style={{ fontSize: "0.8125rem", color: "var(--color-text-secondary)", marginBottom: 16 }}>
        账户余额：<strong style={{ color: "var(--color-primary)", fontSize: "1rem" }}>¥{formatPrice(balance)}</strong>
      </div>

      {activeTab === "buy" && (
        <>
          {/* 充值套餐 */}
          {grouped.recharge && (
            <div className={styles.section}>
              <h3 className={styles.sectionTitle}>{typeLabels.recharge}</h3>
              <p className={styles.sectionDesc}>充值即赠送，多充多送</p>
              <div className={styles.planGrid}>
                {grouped.recharge.map((p) => (
                  <div key={p.id} className={styles.planCard}>
                    <div className={styles.planName}>{p.name}</div>
                    <div className={styles.planPrice}>
                      ¥{formatPrice(p.price)}
                      <span className={styles.planPriceUnit}> / 实得 ¥{formatPrice(p.price + (p.bonusAmount ?? 0))}</span>
                    </div>
                    <div className={styles.planMeta}>赠送 ¥{formatPrice(p.bonusAmount ?? 0)}</div>
                    {p.description && <div className={styles.planDesc}>{p.description}</div>}
                    <button
                      className={styles.buyBtn}
                      disabled={isOwned(p) || balance < p.price}
                      onClick={() => handleBuy(p)}
                    >
                      {isOwned(p) ? "已拥有" : balance < p.price ? "余额不足" : "立即购买"}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Token 套餐 */}
          {grouped.token && (
            <div className={styles.section}>
              <h3 className={styles.sectionTitle}>{typeLabels.token}</h3>
              <p className={styles.sectionDesc}>按量购买，先用后付</p>
              <div className={styles.planGrid}>
                {grouped.token.map((p) => (
                  <div key={p.id} className={styles.planCard}>
                    <div className={styles.planName}>{p.name}</div>
                    <div className={styles.planPrice}>
                      ¥{formatPrice(p.price)}
                      <span className={styles.planPriceUnit}> / {formatToken(p.tokenAmount)} tokens</span>
                    </div>
                    <div className={styles.planMeta}>
                      {p.serviceType ? `仅限：${serviceLabels[p.serviceType] ?? p.serviceType}` : "全场通用"}
                      {p.validityDays ? ` · ${p.validityDays}天有效` : ""}
                    </div>
                    {p.description && <div className={styles.planDesc}>{p.description}</div>}
                    <button
                      className={styles.buyBtn}
                      disabled={isOwned(p) || balance < p.price}
                      onClick={() => handleBuy(p)}
                    >
                      {isOwned(p) ? "已拥有" : balance < p.price ? "余额不足" : "立即购买"}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 订阅套餐 */}
          {grouped.subscription && (
            <div className={styles.section}>
              <h3 className={styles.sectionTitle}>{typeLabels.subscription}</h3>
              <p className={styles.sectionDesc}>按月订阅，每月刷新额度</p>
              <div className={styles.planGrid}>
                {grouped.subscription.map((p) => (
                  <div key={p.id} className={styles.planCard}>
                    <div className={styles.planName}>{p.name}</div>
                    <div className={styles.planPrice}>
                      ¥{formatPrice(p.price)}
                      <span className={styles.planPriceUnit}> / 月 · {formatToken(p.tokenAmount)} tokens</span>
                    </div>
                    <div className={styles.planMeta}>
                      {p.serviceType ? `仅限：${serviceLabels[p.serviceType] ?? p.serviceType}` : "全场通用"}
                      {p.autoRenew ? " · 到期自动续费" : ""}
                    </div>
                    {p.description && <div className={styles.planDesc}>{p.description}</div>}
                    <button
                      className={styles.buyBtn}
                      disabled={ownedPlanIds.has(p.id) || balance < p.price}
                      onClick={() => handleBuy(p)}
                    >
                      {ownedPlanIds.has(p.id) ? "已订阅" : balance < p.price ? "余额不足" : "立即订阅"}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {plans.length === 0 && (
            <p style={{ textAlign: "center", color: "var(--color-text-tertiary)", paddingTop: 40 }}>暂无可购买的套餐</p>
          )}
        </>
      )}

      {activeTab === "mine" && (
        <div>
          {userPlans.length === 0 ? (
            <p style={{ textAlign: "center", color: "var(--color-text-tertiary)", paddingTop: 40 }}>还没有购买过套餐</p>
          ) : (
            <div className={styles.userPlans}>
              {userPlans.map((up) => {
                const isRecharge = up.totalTokens === 0;
                const usedPct = isRecharge ? 0 : Math.min(100, Math.round((up.usedTokens / up.totalTokens) * 100));
                return (
                  <div key={up.id} className={styles.userPlanItem}>
                    <div className={styles.userPlanInfo}>
                      <div className={styles.userPlanName}>
                        {up.plan.name}
                        <span style={{
                          fontSize: 11, marginLeft: 8, padding: "1px 6px", borderRadius: 4,
                          background: up.status === "active" ? (isRecharge ? "#f6ffed" : "#e6f7ff") : "#f5f5f5",
                          color: up.status === "active" ? (isRecharge ? "#52c41a" : "#1890ff") : "#999",
                          border: "1px solid",
                          borderColor: up.status === "active" ? (isRecharge ? "#b7eb8f" : "#91d5ff") : "#e8e8e8",
                        }}>
                          {isRecharge ? "已生效" : up.status === "active" ? "使用中" : up.status === "exhausted" ? "已用完" : up.status === "expired" ? "已过期" : "已取消"}
                        </span>
                      </div>
                      <div className={styles.userPlanTokens}>
                        {isRecharge ? (
                          <span style={{ color: "#52c41a" }}>充值已到账</span>
                        ) : (
                          <>
                            已用 {up.usedTokens.toLocaleString()} / 共 {up.totalTokens.toLocaleString()} tokens
                            {up.plan.type === "subscription" && up.currentPeriodEnd && (
                              <span> · 周期至 {new Date(up.currentPeriodEnd).toLocaleDateString("zh-CN")}</span>
                            )}
                            {up.expiresAt && (
                              <span> · 有效期至 {new Date(up.expiresAt).toLocaleDateString("zh-CN")}</span>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                    {!isRecharge && (
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        {up.plan.type === "subscription" && up.plan.isActive && (
                          <button
                            onClick={() => handleToggleAutoRenew(up.id, !!up.autoRenew)}
                            disabled={togglingId === up.id}
                            style={{
                              fontSize: "0.75rem", padding: "4px 10px", borderRadius: 4,
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
                        <div className={styles.progressBar}>
                          <div className={styles.progressFill} style={{ width: `${usedPct}%` }} />
                        </div>
                        <span style={{ fontSize: 12, color: "var(--color-text-tertiary)", minWidth: 36 }}>{usedPct}%</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── 支付弹窗 ── */}
      <Modal
        title="选择支付方式"
        open={payModalOpen}
        onCancel={handleCancelPay}
        footer={null}
        destroyOnHidden
        width={400}
      >
        {payPlan && (
          <div style={{ marginBottom: 16, padding: "0.75rem 1rem", background: "var(--color-bg)", borderRadius: 6 }}>
            <div style={{ fontWeight: 600, fontSize: "0.9375rem", marginBottom: 4 }}>{payPlan.name}</div>
            <div style={{ fontSize: "0.8125rem", color: "var(--color-text-secondary)" }}>
              金额：<strong style={{ color: "var(--color-primary)", fontSize: "1rem" }}>¥{formatPrice(payPlan.price)}</strong>
            </div>
          </div>
        )}

        {!pendingOrderId ? (
          <>
            <Radio.Group
              value={payMethod}
              onChange={(e) => setPayMethod(e.target.value)}
              style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}
            >
              <Radio value="balance" style={{ padding: "8px 0" }}>
                <span style={{ fontWeight: 500 }}>余额支付</span>
                <span style={{ marginLeft: 8, fontSize: "0.75rem", color: "var(--color-text-secondary)" }}>
                  余额：¥{formatPrice(balance)}
                </span>
              </Radio>
              <Radio value="alipay" style={{ padding: "8px 0" }}>
                <span style={{ fontWeight: 500 }}>支付宝</span>
                <span style={{ marginLeft: 8, fontSize: "0.75rem", color: "var(--color-text-secondary)" }}>（模拟）</span>
              </Radio>
              <Radio value="wxpay" style={{ padding: "8px 0" }}>
                <span style={{ fontWeight: 500 }}>微信支付</span>
                <span style={{ marginLeft: 8, fontSize: "0.75rem", color: "var(--color-text-secondary)" }}>（模拟）</span>
              </Radio>
            </Radio.Group>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button
                style={{
                  padding: "0.5rem 1rem", borderRadius: 6, border: "1px solid var(--color-border)",
                  background: "var(--color-surface)", cursor: "pointer", fontSize: "0.875rem",
                }}
                onClick={handleCancelPay}
              >
                取消
              </button>
              <button
                style={{
                  padding: "0.5rem 1rem", borderRadius: 6, border: "none",
                  background: "var(--color-primary)", color: "#fff", cursor: "pointer",
                  fontSize: "0.875rem", opacity: payProcessing ? 0.6 : 1,
                }}
                disabled={payProcessing}
                onClick={handleConfirmPay}
              >
                {payProcessing ? "处理中..." : "确认支付"}
              </button>
            </div>
          </>
        ) : (
          <>
            <div style={{
              textAlign: "center", padding: "1rem 0", marginBottom: 16,
            }}>
              <div style={{ fontSize: "0.875rem", color: "var(--color-text-secondary)", marginBottom: 8 }}>
                订单已创建，请完成支付
              </div>
              <div style={{
                display: "inline-block", padding: "0.5rem 1.5rem", borderRadius: 8,
                background: "var(--color-surface)",
                border: "1px solid var(--color-border)", fontSize: "0.8125rem",
              }}>
                订单号：{pendingOrderId.slice(0, 8)}...
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button
                style={{
                  padding: "0.5rem 1rem", borderRadius: 6, border: "1px solid var(--color-border)",
                  background: "var(--color-surface)", cursor: "pointer", fontSize: "0.875rem",
                }}
                onClick={handleCancelPay}
              >
                取消
              </button>
              <button
                style={{
                  padding: "0.5rem 1rem", borderRadius: 6, border: "none",
                  background: "#52c41a", color: "#fff", cursor: "pointer",
                  fontSize: "0.875rem", fontWeight: 500, opacity: payProcessing ? 0.6 : 1,
                }}
                disabled={payProcessing}
                onClick={handleMockPay}
              >
                {payProcessing ? "处理中..." : "模拟支付"}
              </button>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}