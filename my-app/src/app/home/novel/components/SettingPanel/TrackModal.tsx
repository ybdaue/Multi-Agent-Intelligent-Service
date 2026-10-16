"use client";

import { useEffect } from "react";
import { CloseOutlined } from "@ant-design/icons";
import type { Chain } from "./chains";
import { EMPTY_PLACEHOLDER, fieldText, type PanelSpec, type Row } from "./specs";
import styles from "./TrackModal.module.scss";

interface TrackModalProps {
  spec: PanelSpec;
  /** 要看轨迹的那条链（头 → 尾）；null 表示没打开 */
  chain: Chain | null;
  onClose: () => void;
}

/** 这一版里哪些字段的值跟上一版不一样 —— 用来把"这一版改了什么"标出来。头一版没有上一版，全不标。 */
function changedKeys(spec: PanelSpec, version: Row, prev: Row | undefined): Set<string> {
  const changed = new Set<string>();
  if (!prev) return changed;
  for (const field of spec.fields) {
    if (fieldText(field, version) !== fieldText(field, prev)) changed.add(field.key);
  }
  return changed;
}

export default function TrackModal({ spec, chain, onClose }: TrackModalProps) {
  useEffect(() => {
    if (!chain) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [chain, onClose]);

  if (!chain) return null;

  const versions = chain.versions;
  const current = versions[versions.length - 1];

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.header}>
          <div className={styles.title}>
            变化轨迹 · {spec.title(current)}
            <span className={styles.count}>共 {versions.length} 版</span>
          </div>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            title="关闭"
            aria-label="关闭"
          >
            <CloseOutlined />
          </button>
        </div>

        <div className={styles.body}>
          {versions.map((row, index) => {
            const isCurrent = index === versions.length - 1;
            const changed = changedKeys(spec, row, index > 0 ? versions[index - 1] : undefined);
            // 这一版从哪章起生效（后端已把章节 id 转成「第N章 标题」给出来）；没有就按首版 / 未标。
            const chapter =
              String(row.firstAppearanceChapter ?? "").trim() ||
              (index === 0 ? "最初" : "未标注章节");
            return (
              <article
                key={String(row.id ?? index)}
                className={`${styles.version} ${isCurrent ? styles.versionCurrent : ""}`}
              >
                <div className={styles.versionHead}>
                  <span className={styles.chapter}>{chapter}</span>
                  {isCurrent ? <span className={styles.currentTag}>当前</span> : null}
                </div>
                <div className={styles.fields}>
                  {spec.fields.map((field) => (
                    <div
                      key={field.key}
                      className={`${styles.field} ${field.block ? styles.fieldBlock : ""}`}
                    >
                      <span
                        className={`${styles.label} ${
                          changed.has(field.key) ? styles.labelChanged : ""
                        }`}
                      >
                        {field.label}
                      </span>
                      <span className={styles.value}>
                        {fieldText(field, row) || EMPTY_PLACEHOLDER}
                      </span>
                    </div>
                  ))}
                </div>
              </article>
            );
          })}
        </div>

        <div className={styles.footer}>
          <button type="button" className={styles.closeFooterBtn} onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}