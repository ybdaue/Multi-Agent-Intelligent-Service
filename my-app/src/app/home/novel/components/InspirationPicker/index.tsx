"use client";

import { useEffect, useState } from "react";
import { BulbOutlined, CloseOutlined } from "@ant-design/icons";
import type { InspirationItem } from "../types";
import { INSPIRATION_CATEGORY_LABEL, type InspirationCategory } from "../types";
import { useNovelQuery } from "../useNovelQuery";
import styles from "./index.module.scss";

interface PickerRow {
  id: string;
  title: string;
  category: string[];
  type: string;
  content: string;
  usage: string;
  lifecycle: string;
  scenario: string;
  digest: string;
  usedChapterIds: string[];
}

interface InspirationsResponse {
  threadId: string;
  total: number;
  inspirations: PickerRow[];
}

interface InspirationPickerProps {
  threadId: string | null;
  onClose: () => void;
  /** 挑中的灵感：kind 一律 text、name 取标题、inspirationId 带上库内 id，随对话发出去 */
  onConfirm: (items: InspirationItem[]) => void;
}

/** 对话里挑灵感：只列「选用」的（必用不必挑、不用不给挑），挑中的本轮新章必须用。 */
export default function InspirationPicker({
  threadId,
  onClose,
  onConfirm,
}: InspirationPickerProps) {
  const url = threadId
    ? `/api/novel/method/inspirations?threadId=${encodeURIComponent(threadId)}`
    : null;
  const { data, loading, error } = useNovelQuery<InspirationsResponse>(url);
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  // 只给「选用」的挑；单次且已用过的退出候选（跟 planner 的菜单口径一致）。
  const rows = (data?.inspirations ?? []).filter(
    (row) => row.usage === "selectable" && !(row.lifecycle === "once" && row.usedChapterIds.length > 0),
  );

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const confirm = () => {
    const items: InspirationItem[] = rows
      .filter((row) => selected.includes(row.id))
      .map((row) => ({
        id: `pick-${row.id}`,
        kind: "text",
        name: row.title || row.content.slice(0, 20) || "灵感",
        inspirationId: row.id,
      }));
    onConfirm(items);
    onClose();
  };

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label="从灵感库挑选"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.header}>
          <span className={styles.title}>
            <BulbOutlined /> 从灵感库挑选
          </span>
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

        <div className={styles.hintLine}>
          只列「选用」的灵感。挑中的，这一轮新写的章节**必须用上**；必用的灵感不受影响、照旧全带上。
        </div>

        <div className={styles.listWrap}>
          {loading ? (
            <div className={styles.emptyHint}>加载中…</div>
          ) : error ? (
            <div className={styles.emptyHint}>加载失败：{error}</div>
          ) : rows.length === 0 ? (
            <div className={styles.emptyHint}>
              没有可挑选的灵感。去灵感库把想要的那条标成「选用」再来。
            </div>
          ) : (
            <ul className={styles.list}>
              {rows.map((row) => {
                const on = selected.includes(row.id);
                return (
                  <li
                    key={row.id}
                    className={`${styles.item} ${on ? styles.itemOn : ""}`}
                    onClick={() => toggle(row.id)}
                  >
                    <span className={`${styles.check} ${on ? styles.checkOn : ""}`}>
                      {on ? "✓" : ""}
                    </span>
                    <div className={styles.itemBody}>
                      <div className={styles.itemHead}>
                        <span className={styles.itemTitle}>
                          {row.title || row.content.slice(0, 20) || "（未命名）"}
                        </span>
                        {(row.category ?? []).map((c) => (
                          <span key={c} className={styles.catTag}>
                            {INSPIRATION_CATEGORY_LABEL[c as InspirationCategory] ?? c}
                          </span>
                        ))}
                        {row.usedChapterIds.length > 0 && (
                          <span className={styles.usedTag}>已用过</span>
                        )}
                      </div>
                      {row.scenario && <div className={styles.itemLine}>场景：{row.scenario}</div>}
                      {row.digest && <div className={styles.itemLine}>指引：{row.digest}</div>}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className={styles.footer}>
          <button type="button" className={styles.cancelBtn} onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className={styles.confirmBtn}
            onClick={confirm}
            disabled={selected.length === 0}
          >
            选好了（{selected.length}）
          </button>
        </div>
      </div>
    </div>
  );
}