"use client";

import { useCallback, useEffect, useState } from "react";
import { Spin, Alert } from "antd";
import type { RecentBillingItem } from "../types/dashboard";
import { fetchRecentBilling } from "../../api/admin/dashboard";
import styles from "../page.module.scss";

const fmtPrice = (cents: number) => `¥${(cents / 100).toFixed(2)}`;

export default function RecentBillingList() {
  const [data, setData] = useState<RecentBillingItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchRecentBilling(10));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} />;
  }

  return (
    <div className={styles.tableCard}>
      <h4 className={styles.tableTitle}>最近消费记录</h4>
      {loading ? (
        <div className={styles.tableEmpty}>
          <Spin />
        </div>
      ) : data.length === 0 ? (
        <div className={styles.tableEmpty}>暂无消费记录</div>
      ) : (
        <div className={styles.billingList}>
          {data.map((b) => (
            <div key={b.id} className={styles.billingItem}>
              <div>
                <div className={styles.billingUser}>{b.userEmail}</div>
                <div className={styles.billingMeta}>
                  {b.serviceType} · {b.createdAt?.slice(0, 19).replace("T", " ")}
                </div>
              </div>
              <div className={styles.billingAmount}>{fmtPrice(b.totalCost)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}