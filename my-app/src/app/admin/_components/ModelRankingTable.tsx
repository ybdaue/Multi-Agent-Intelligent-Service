"use client";

import { useCallback, useEffect, useState } from "react";
import { Spin, Alert, Table, Tag } from "antd";
import type { ModelRankingItem, TimeContext } from "../types/dashboard";
import { fetchModelRanking } from "../../api/admin/dashboard";
import styles from "../page.module.scss";

interface Props {
  timeContext: TimeContext;
}

const fmtPrice = (v: number) => `¥${(v / 100).toFixed(2)}`;
const fmtTokens = (v: number) => (v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` : v >= 1_000 ? `${(v / 1_000).toFixed(1)}K` : String(v));

const columns = [
  {
    title: "模型",
    dataIndex: "modelName",
    key: "modelName",
    ellipsis: true,
    render: (v: string) => <span style={{ fontWeight: 500 }}>{v}</span>,
  },
  {
    title: "服务",
    dataIndex: "serviceType",
    key: "serviceType",
    width: 80,
    render: (v: string) => <Tag>{v}</Tag>,
  },
  {
    title: "调用次数",
    dataIndex: "callCount",
    key: "callCount",
    width: 100,
    sorter: (a: ModelRankingItem, b: ModelRankingItem) => a.callCount - b.callCount,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: "总费用",
    dataIndex: "totalCost",
    key: "totalCost",
    width: 110,
    sorter: (a: ModelRankingItem, b: ModelRankingItem) => a.totalCost - b.totalCost,
    render: (v: number) => fmtPrice(v),
    defaultSortOrder: "descend" as const,
  },
  {
    title: "Input Tokens",
    dataIndex: "inputTokens",
    key: "inputTokens",
    width: 120,
    render: (v: number) => fmtTokens(v),
  },
  {
    title: "Output Tokens",
    dataIndex: "outputTokens",
    key: "outputTokens",
    width: 120,
    render: (v: number) => fmtTokens(v),
  },
];

export default function ModelRankingTable({ timeContext }: Props) {
  const [data, setData] = useState<ModelRankingItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchModelRanking(timeContext));
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
      <h4 className={styles.tableTitle}>模型消费排行</h4>
      <Table
        dataSource={data}
        columns={columns}
        rowKey="modelName"
        loading={loading}
        size="small"
        pagination={false}
      />
    </div>
  );
}