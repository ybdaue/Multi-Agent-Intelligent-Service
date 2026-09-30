"use client";

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import type { TrendItem } from "../types/dashboard";
import styles from "../page.module.scss";

const formatDate = (d: string) =>
  d.length === 7 ? `${parseInt(d.slice(5), 10)}月` : d.slice(5);

const fmtYuan = (v: number) => `¥${(v / 100).toFixed(2)}`;

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className={styles.chartTooltip}>
      <div className={styles.tooltipDate}>{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ color: p.color }}>
          {p.name}: {fmtYuan(p.value)}
        </div>
      ))}
    </div>
  );
};

export default function UserRechargeTrendChart({ data }: { data: TrendItem[] }) {
  if (!data.length) {
    return <div className={styles.chartCard}><div className={styles.chartEmpty}>暂无用户充值数据</div></div>;
  }
  return (
    <div className={styles.chartCard}>
      <h4 className={styles.chartTitle}>用户充值趋势</h4>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }} />
          <YAxis tickFormatter={(v) => `¥${(v / 100).toFixed(0)}`} tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }} />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="userRecharge" name="用户充值" fill="#10b981" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}