"use client";

import { useState } from "react";
import { useNovelQuery } from "../useNovelQuery";
import { buildChains, type Chain } from "./chains";
import { EMPTY_PLACEHOLDER, fieldText, type PanelSpec, type Row } from "./specs";
import TrackModal from "./TrackModal";
import styles from "./index.module.scss";

interface SettingPanelProps {
  threadId: string | null;
  spec: PanelSpec;
}

interface PanelResponse {
  total?: number;
  [key: string]: unknown;
}

export default function SettingPanel({ threadId, spec }: SettingPanelProps) {
  const url = threadId
    ? `/api/novel/method/${spec.endpoint}?threadId=${encodeURIComponent(threadId)}`
    : null;
  const { data, loading, error } = useNovelQuery<PanelResponse>(url);
  /** 正开着变化轨迹的那条链，null 表示没开 */
  const [track, setTrack] = useState<Chain | null>(null);

  if (!threadId) return <div className={styles.hint}>请先在左侧选择小说</div>;
  if (loading) return <div className={styles.hint}>加载中…</div>;
  if (error) return <div className={styles.hint}>加载失败：{error}</div>;

  const rows = (data?.[spec.listKey] as Row[] | undefined) ?? [];
  if (rows.length === 0) return <div className={styles.hint}>{spec.empty}</div>;

  // 会演变的设定（人物 / 世界观 / 势力 / 物品 / 关系）：按 next 串链，一链一张卡、只摆当前版
  // （链尾），多版的收起「变化轨迹」按钮；其余标签页仍一行一张卡。
  const chains = spec.versioned ? buildChains(rows) : rows.map((row) => ({ versions: [row] }));

  return (
    <div className={styles.panel}>
      <div className={styles.summary}>共 {chains.length} 项</div>
      <div className={styles.cards}>
        {chains.map((chain, index) => {
          const row = chain.versions[chain.versions.length - 1];
          const changes = chain.versions.length - 1;
          return (
            <article key={String(row.id ?? index)} className={styles.card}>
              <div className={styles.cardHead}>
                <div className={styles.cardTitle}>{spec.title(row)}</div>
                {changes > 0 ? (
                  <span className={styles.changeTag}>已变化 {changes} 次</span>
                ) : null}
              </div>
              <div className={styles.fields}>
                {spec.fields.map((field) => {
                  const value = fieldText(field, row);
                  return (
                    <div
                      key={field.key}
                      className={`${styles.field} ${field.block ? styles.fieldBlock : ""}`}
                    >
                      <span className={styles.label}>{field.label}</span>
                      <span className={styles.value}>{value || EMPTY_PLACEHOLDER}</span>
                    </div>
                  );
                })}
              </div>
              {changes > 0 ? (
                <div className={styles.trackRow}>
                  <button
                    type="button"
                    className={styles.trackBtn}
                    onClick={() => setTrack(chain)}
                  >
                    查看变化轨迹 ▸
                  </button>
                </div>
              ) : null}
            </article>
          );
        })}
      </div>

      <TrackModal spec={spec} chain={track} onClose={() => setTrack(null)} />
    </div>
  );
}