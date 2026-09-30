"use client";

import { useCallback, useEffect, useState } from "react";
import { Spin, Alert, Table, Tag } from "antd";
import type { UserTopItem, TimeContext } from "../types/dashboard";
import { fetchUserTop } from "../../api/admin/dashboard";
import styles from "../page.module.scss";

interface Props {
  timeContext: TimeContext;
}

const fmtPrice = (v: number) => `¥${(v / 100).toFixed(2)}`;

const columns = [
  {
    title: "排名",
    key: "rank",
    width: 50,
    render: (_: unknown, __: unknown, i: number) => (
      <span style={{ fontWeight: 600, color: i < 3 ? "var(--color-primary)" : undefined }}>
        {i + 1}
      </span>
    ),
  },
  {
    title: "用户",
    dataIndex: "userEmail",
    key: "userEmail",
    ellipsis: true,
    render: (v: string, r: UserTopItem) => (
      <span title={v}>
        {r.userName || v}
      </span>
    ),
  },
  {
    title: "消费次数",
    dataIndex: "billingCount",
    key: "billingCount",
    width: 90,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: "总消费",
    dataIndex: "totalCost",
    key: "totalCost",
    width: 110,
    render: (v: number) => <span style={{ fontWeight: 600 }}>{fmtPrice(v)}</span>,
    defaultSortOrder: "descend" as const,
  },
];

export default function UserTopTable({ timeContext }: Props) {
  const [data, setData] = useState<UserTopItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchUserTop(timeContext));
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
      <h4 className={styles.tableTitle}>用户消费 TOP10</h4>
      <Table
        dataSource={data}
        columns={columns}
        rowKey="userId"
        loading={loading}
        size="small"
        pagination={false}
      />
    </div>
  );
}