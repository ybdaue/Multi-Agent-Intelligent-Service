"use client";

import { useCallback, useEffect, useState } from "react";
import { Spin, Alert, Table } from "antd";
import type { TrendItem, TimeContext } from "../types/dashboard";
import { fetchTrends } from "../../api/admin/dashboard";
import styles from "../page.module.scss";

interface Props {
  timeContext: TimeContext;
}

const fmtDate = (d: string) =>
  d.length === 7
    ? `${d.slice(0, 4)}年${parseInt(d.slice(5), 10)}月`
    : `${parseInt(d.slice(5, 7), 10)}月${parseInt(d.slice(8), 10)}日`;

const columns = [
  {
    title: "日期",
    dataIndex: "date",
    key: "date",
    width: 90,
    render: (v: string) => <span style={{ fontWeight: 500 }}>{fmtDate(v)}</span>,
  },
  {
    title: "登录活跃",
    dataIndex: "loginDau",
    key: "loginDau",
    width: 100,
    sorter: (a: TrendItem, b: TrendItem) => a.loginDau - b.loginDau,
    render: (v: number) => v.toLocaleString(),
    defaultSortOrder: "descend" as const,
  },
  {
    title: "新增用户",
    dataIndex: "newUsers",
    key: "newUsers",
    width: 90,
    render: (v: number) => v.toLocaleString(),
  },
];

export default function ActiveUserTable({ timeContext }: Props) {
  const [data, setData] = useState<TrendItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { range, year, month } = timeContext;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchTrends({ range, year, month });
      setData(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [range, year, month]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} />;
  }

  return (
    <div className={styles.chartCard}>
      <h4 className={styles.chartTitle}>活跃用户明细</h4>
      {loading ? (
        <div className={styles.chartEmpty}><Spin /></div>
      ) : (
        <Table
          dataSource={data.slice(-15)}
          columns={columns}
          rowKey="date"
          size="small"
          pagination={false}
          scroll={{ y: 280 }}
        />
      )}
    </div>
  );
}