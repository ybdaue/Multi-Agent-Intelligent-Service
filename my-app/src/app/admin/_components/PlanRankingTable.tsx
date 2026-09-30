"use client";

import { useCallback, useEffect, useState } from "react";
import { Alert, Table, Tag } from "antd";
import type { PlanRankingItem, TimeContext } from "../types/dashboard";
import { fetchPlanRanking } from "../../api/admin/dashboard";
import styles from "../page.module.scss";

interface Props {
  timeContext: TimeContext;
}

const fmtPrice = (v: number) => `¥${(v / 100).toFixed(2)}`;

const planTypeLabels: Record<string, { label: string; color: string }> = {
  recharge: { label: "充值", color: "green" },
  token: { label: "Token", color: "blue" },
  subscription: { label: "订阅", color: "purple" },
};

const columns = [
  {
    title: "套餐名",
    dataIndex: "planName",
    key: "planName",
    ellipsis: true,
    render: (v: string) => <span style={{ fontWeight: 500 }}>{v || "未知套餐"}</span>,
  },
  {
    title: "类型",
    dataIndex: "planType",
    key: "planType",
    width: 70,
    render: (v: string) => {
      const cfg = planTypeLabels[v] || { label: v, color: "default" };
      return <Tag color={cfg.color}>{cfg.label}</Tag>;
    },
  },
  {
    title: "单价",
    dataIndex: "price",
    key: "price",
    width: 80,
    render: (v: number) => fmtPrice(v),
  },
  {
    title: "销量",
    dataIndex: "soldCount",
    key: "soldCount",
    width: 80,
    sorter: (a: PlanRankingItem, b: PlanRankingItem) => a.soldCount - b.soldCount,
    render: (v: number) => <span style={{ fontWeight: 600 }}>{v.toLocaleString()}</span>,
    defaultSortOrder: "descend" as const,
  },
  {
    title: "总收入",
    dataIndex: "totalRevenue",
    key: "totalRevenue",
    width: 110,
    render: (v: number) => fmtPrice(v),
  },
];

export default function PlanRankingTable({ timeContext }: Props) {
  const [data, setData] = useState<PlanRankingItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchPlanRanking(timeContext));
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
    return <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} />;
  }

  return (
    <div className={styles.tableCard}>
      <h4 className={styles.tableTitle}>套餐销量排行</h4>
      <Table
        dataSource={data}
        columns={columns}
        rowKey="planId"
        loading={loading}
        size="small"
        pagination={false}
      />
    </div>
  );
}