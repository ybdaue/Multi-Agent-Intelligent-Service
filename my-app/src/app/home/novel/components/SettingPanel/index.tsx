"use client";

import { useNovelQuery } from "../useNovelQuery";
import type { PanelSpec, Row } from "./specs";
import styles from "./index.module.scss";

interface SettingPanelProps {
  threadId: string | null;
  spec: PanelSpec;
}

interface PanelResponse {
  total?: number;
  [key: string]: unknown;
}

/** 值转成能显示的一串：数组拼顿号，空值给空串（空字段整条不显示）。 */
function display(value: unknown) {
  if (Array.isArray(value)) return value.length ? value.join("、") : "";
  if (value == null || value === "") return "";
  return String(value);
}

export default function SettingPanel({ threadId, spec }: SettingPanelProps) {
  const url = threadId
    ? `/api/novel/method/${spec.endpoint}?threadId=${encodeURIComponent(threadId)}`
    : null;
  const { data, loading, error } = useNovelQuery<PanelResponse>(url);

  if (!threadId) return <div className={styles.hint}>请先在左侧选择小说</div>;
  if (loading) return <div className={styles.hint}>加载中…</div>;
  if (error) return <div className={styles.hint}>加载失败：{error}</div>;

  const rows = (data?.[spec.listKey] as Row[] | undefined) ?? [];
  if (rows.length === 0) return <div className={styles.hint}>{spec.empty}</div>;

  return (
    <div className={styles.panel}>
      <div className={styles.summary}>共 {rows.length} 条</div>
      <div className={styles.cards}>
        {rows.map((row, index) => (
          <article key={String(row.id ?? index)} className={styles.card}>
            <div className={styles.cardTitle}>{spec.title(row)}</div>
            <div className={styles.fields}>
              {spec.fields.map((field) => {
                const value = field.format
                  ? field.format(row[field.key], row)
                  : display(row[field.key]);
                if (!value) return null;
                return (
                  <div
                    key={field.key}
                    className={`${styles.field} ${field.block ? styles.fieldBlock : ""}`}
                  >
                    <span className={styles.label}>{field.label}</span>
                    <span className={styles.value}>{value}</span>
                  </div>
                );
              })}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
