"use client";

import { useCallback, useEffect, useState } from "react";
import { Spin, Alert } from "antd";
import {
  UserOutlined,
  BookOutlined,
  TeamOutlined,
  DollarOutlined,
  WalletOutlined,
  ClockCircleOutlined,
  BankOutlined,
  GiftOutlined,
  ToolOutlined,
  MinusCircleOutlined,
} from "@ant-design/icons";
import type { DashboardSummary, TimeContext } from "../types/dashboard";
import { fetchSummary } from "../../api/admin/dashboard";
import styles from "../page.module.scss";

interface Props {
  timeContext: TimeContext;
}

const fmtYuan = (v: number) => `¥${(v / 100).toFixed(2)}`;

const row1Cards: {
  key: keyof DashboardSummary;
  label: string;
  icon: React.ReactNode;
  fmt?: (v: number) => string;
}[] = [
  { key: "userCount", label: "用户总数", icon: <UserOutlined /> },
  { key: "novelCount", label: "小说总数", icon: <BookOutlined /> },
  { key: "paidUserCount", label: "付费用户数", icon: <TeamOutlined /> },
  { key: "totalRevenue", label: "总模型费用", icon: <DollarOutlined />, fmt: fmtYuan },
  { key: "totalRecharge", label: "总充值", icon: <WalletOutlined />, fmt: fmtYuan },
  { key: "pendingOrderCount", label: "待处理订单", icon: <ClockCircleOutlined /> },
];

const row2Cards: {
  key: keyof DashboardSummary;
  label: string;
  icon: React.ReactNode;
  fmt?: (v: number) => string;
}[] = [
  { key: "realRevenue", label: "实收收入", icon: <BankOutlined />, fmt: fmtYuan },
  { key: "bonusAmount", label: "赠送充值", icon: <GiftOutlined />, fmt: fmtYuan },
  { key: "adminRecharge", label: "管理员充值", icon: <ToolOutlined />, fmt: fmtYuan },
  { key: "adminDeduction", label: "管理员扣款", icon: <MinusCircleOutlined />, fmt: fmtYuan },
  { key: "todayRevenue", label: "今日收入", icon: <DollarOutlined />, fmt: fmtYuan },
  { key: "todayRecharge", label: "今日充值", icon: <WalletOutlined />, fmt: fmtYuan },
];

function CardRow({
  cards,
  data,
  loading,
}: {
  cards: typeof row1Cards;
  data: DashboardSummary | null;
  loading: boolean;
}) {
  return (
    <div className={styles.statGrid}>
      {cards.map((c) => (
        <div key={c.key} className={styles.statCard}>
          <div className={styles.statIcon}>{c.icon}</div>
          <div>
            <div className={styles.statLabel}>{c.label}</div>
            <div className={styles.statValue}>
              {loading || !data ? (
                <Spin size="small" />
              ) : c.fmt ? (
                c.fmt(data[c.key])
              ) : (
                data[c.key].toLocaleString()
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function StatCards({ timeContext }: Props) {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchSummary(timeContext);
      setData(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [timeContext]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return (
      <Alert
        type="error"
        message="统计加载失败"
        description={error}
        showIcon
        closable
        onClose={() => setError(null)}
      />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
      <CardRow cards={row1Cards} data={data} loading={loading} />
      <CardRow cards={row2Cards} data={data} loading={loading} />
    </div>
  );
}