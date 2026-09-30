"use client";

import { useCallback, useEffect, useState } from "react";
import { Spin, Alert, Table, Tag, Progress } from "antd";
import type { ServiceDistribution, TimeContext } from "../types/dashboard";
import { fetchServiceRanking } from "../../api/admin/dashboard";
import styles from "../page.module.scss";

interface Props {
  timeContext: TimeContext;
}

const serviceLabels: Record<string, string> = {
  novel: "小说",
  legal: "法律",
  finance: "金融",
  chat: "闲聊",
};

const serviceColors: Record<string, string> = {
  novel: "#3b82f6",
  legal: "#10b981",
  finance: "#f59e0b",
  chat: "#8b5cf6",
};

const fmtPrice = (v: number) => `¥${(v / 100).toFixed(2)}`;

export default function ServiceRankingTable({ timeContext }: Props) {
  const [data, setData] = useState<ServiceDistribution[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchServiceRanking(timeContext));
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

  const columns = [
    {
      title: "服务",
      dataIndex: "serviceType",
      key: "serviceType",
      render: (v: string) => (
        <Tag color={serviceColors[v]}>{serviceLabels[v] ?? v}</Tag>
      ),
    },
    {
      title: "调用次数",
      dataIndex: "callCount",
      key: "callCount",
      width: 110,
      sorter: (a: ServiceDistribution, b: ServiceDistribution) => a.callCount - b.callCount,
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: "总费用",
      dataIndex: "totalCost",
      key: "totalCost",
      width: 120,
      sorter: (a: ServiceDistribution, b: ServiceDistribution) => a.totalCost - b.totalCost,
      render: (v: number) => fmtPrice(v),
      defaultSortOrder: "descend" as const,
    },
    {
      title: "占比",
      dataIndex: "percentage",
      key: "percentage",
      width: 180,
      render: (v: number) => (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Progress percent={v} size="small" style={{ flex: 1, margin: 0 }} />
          <span style={{ fontSize: "0.75rem", color: "var(--color-text-secondary)", whiteSpace: "nowrap" }}>{v}%</span>
        </div>
      ),
    },
  ];

  return (
    <div className={styles.tableCard}>
      <h4 className={styles.tableTitle}>服务消费排行</h4>
      {loading ? (
        <div className={styles.tableEmpty}><Spin /></div>
      ) : (
        <Table
          dataSource={data}
          columns={columns}
          rowKey="serviceType"
          size="small"
          pagination={false}
        />
      )}
    </div>
  );
}