"use client";

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
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

export default function NovelTrendChart({ data }: { data: TrendItem[] }) {
  if (!data.length) {
    return <div className={styles.chartEmpty}>暂无小说数据</div>;
  }
  return (
    <div className={styles.chartCard}>
      <h4 className={styles.chartTitle}>小说 & 章节趋势</h4>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }} />
          <YAxis tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }} />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          <Line type="monotone" dataKey="newNovels" name="新建小说" stroke="#6366f1" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="newChapters" name="新建章节" stroke="#06b6d4" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}