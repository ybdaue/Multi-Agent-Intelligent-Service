"use client";

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";
import type { ServiceDistribution } from "../types/dashboard";
import styles from "../page.module.scss";

const COLORS = ["#6366f1", "#06b6d4", "#f59e0b", "#ef4444", "#10b981", "#8b5cf6", "#ec4899"];

const renderLabel = ({ name, percent }: any) =>
  `${name} ${(percent * 100).toFixed(0)}%`;

const CustomTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className={styles.chartTooltip}>
      <div>{d.serviceType}</div>
      <div>金额: ¥{(d.totalCost / 100).toFixed(2)}</div>
      <div>占比: {d.percentage}%</div>
    </div>
  );
};

export default function ServiceDistributionChart({ data }: { data: ServiceDistribution[] }) {
  if (!data.length) {
    return <div className={styles.chartEmpty}>暂无分布数据</div>;
  }
  return (
    <div className={styles.chartCard}>
      <h4 className={styles.chartTitle}>服务消费分布</h4>
      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie
            data={data}
            dataKey="totalCost"
            nameKey="serviceType"
            cx="50%"
            cy="50%"
            outerRadius={80}
            label={renderLabel}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip content={<CustomTooltip />} />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}