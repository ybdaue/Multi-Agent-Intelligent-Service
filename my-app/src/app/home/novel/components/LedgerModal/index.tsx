"use client";

import { useEffect } from "react";
import { CloseOutlined, ProfileOutlined } from "@ant-design/icons";
import type { Chapter } from "../types";
import { useNovelQuery } from "../useNovelQuery";
import styles from "./index.module.scss";

interface LedgerRef {
  refType: string;
  refTypeLabel: string;
  refId: string;
  name: string;
  role: string;
  roleLabel: string;
}

interface LedgerResponse {
  threadId: string;
  chapterId: string;
  chapterTitle: string;
  chapterOrder: number;
  total: number;
  refs: LedgerRef[];
}

interface LedgerModalProps {
  threadId: string | null;
  /** 要看台账的那一章，null 表示没打开 */
  chapter: Chapter | null;
  onClose: () => void;
}

/**
 * 这一章的台账：写这一章时用到、新造了哪些设定（novel_chapter_ref，由 writer 落库）。
 * 改设定时"哪些章会受波及"就是反查它算出来的，所以前端也按这条线展示。
 */
export default function LedgerModal({ threadId, chapter, onClose }: LedgerModalProps) {
  const url =
    threadId && chapter
      ? `/api/novel/method/chapter/ledger?threadId=${encodeURIComponent(threadId)}` +
        `&chapterId=${encodeURIComponent(chapter.id)}`
      : null;
  const { data, loading, error } = useNovelQuery<LedgerResponse>(url);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  if (!chapter) return null;

  const refs = data?.refs ?? [];

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
            台账 · {chapter.title}
            {data ? <span className={styles.count}>共 {data.total} 条</span> : null}
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
          {loading ? (
            <div className={styles.hint}>加载中…</div>
          ) : error ? (
            <div className={styles.hint}>加载失败：{error}</div>
          ) : refs.length === 0 ? (
            <div className={styles.hint}>
              这一章还没报过关联。写完这一章后，用到和新造的设定都会记在这里。
            </div>
          ) : (
            <ul className={styles.list}>
              {refs.map((ref) => (
                <li key={`${ref.refType}-${ref.refId}`} className={styles.item}>
                  <ProfileOutlined className={styles.itemIcon} />
                  <span className={styles.name}>
                    {ref.name || "（已不存在的对象）"}
                  </span>
                  <span className={styles.type}>{ref.refTypeLabel}</span>
                  {ref.roleLabel ? (
                    <span className={styles.role}>{ref.roleLabel}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
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
