"use client";

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import type { TrendItem } from "../types/dashboard";
import styles from "../page.module.scss";

const formatDate = (d: string) =>
  d.length === 7 ? `${parseInt(d.slice(5), 10)}月` : d.slice(5);

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className={styles.chartTooltip}>
      <div className={styles.tooltipDate}>{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ color: p.color }}>
          {p.name}: {p.value.toLocaleString()}
        </div>
      ))}
    </div>
  );
};

export default function UserRechargeChart({
  data,
  metric = "dau",
  secondaryMetric = "newUsers",
  title = "用户活跃 & 新增",
}: {
  data: TrendItem[];
  metric?: "dau" | "newUsers";
  secondaryMetric?: "dau" | "newUsers";
  title?: string;
}) {
  if (!data.length) {
    return <div className={styles.chartEmpty}>暂无用户数据</div>;
  }
  const metricLabel = metric === "dau" ? "日活用户" : "新增用户";
  const secondaryLabel = secondaryMetric === "newUsers" ? "新增用户" : "日活用户";

  return (
    <div className={styles.chartCard}>
      <h4 className={styles.chartTitle}>{title}</h4>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }} />
          <YAxis tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }} />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          <Bar dataKey={metric} name={metricLabel} fill="var(--color-primary)" radius={[2, 2, 0, 0]} />
          <Bar dataKey={secondaryMetric} name={secondaryLabel} fill="var(--color-primary-light)" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}