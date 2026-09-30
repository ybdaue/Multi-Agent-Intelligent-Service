"use client";

import { useCallback, useEffect, useState } from "react";
import { Spin, Alert } from "antd";
import type { TrendItem, TimeContext } from "../types/dashboard";
import { fetchTrends } from "../../api/admin/dashboard";
import NewUsersChart from "../_charts/NewUsersChart";
import DAUChart from "../_charts/DAUChart";
import ModelCostChart from "../_charts/ModelCostChart";
import RealRevenueChart from "../_charts/RealRevenueChart";
import UserRechargeTrendChart from "../_charts/UserRechargeTrendChart";
import AdminRechargeChart from "../_charts/AdminRechargeChart";
import NovelCountChart from "../_charts/NovelCountChart";
import ChapterCountChart from "../_charts/ChapterCountChart";
import styles from "../page.module.scss";

interface Props {
  timeContext: TimeContext;
}

export default function ChartSection({ timeContext }: Props) {
  const [trends, setTrends] = useState<TrendItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const t = await fetchTrends(timeContext);
      setTrends(t);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "图表加载失败");
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
        message="图表加载失败"
        description={error}
        showIcon
        closable
        onClose={() => setError(null)}
      />
    );
  }

  if (loading) {
    return (
      <div className={styles.chartGrid}>
        {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
          <div key={i} className={styles.chartCard}>
            <div className={styles.chartEmpty}><Spin /></div>
          </div>
        ))}
      </div>
    );
  }

  if (!trends.length) {
    return (
      <div className={styles.chartGrid}>
        <div className={styles.chartCard}>
          <div className={styles.chartEmpty}>当前时间范围无趋势数据</div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.chartGrid}>
      <NewUsersChart data={trends} />
      <DAUChart data={trends} />
      <ModelCostChart data={trends} />
      <RealRevenueChart data={trends} />
      <UserRechargeTrendChart data={trends} />
      <AdminRechargeChart data={trends} />
      <NovelCountChart data={trends} />
      <ChapterCountChart data={trends} />
    </div>
  );
}