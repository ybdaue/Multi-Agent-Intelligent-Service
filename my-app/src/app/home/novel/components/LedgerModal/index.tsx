"use client";

import { useEffect, useMemo } from "react";
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

/** 分组的先后：与后端台账目录（ledger.CATALOG）一致，没列到的类型排到最后。 */
const TYPE_ORDER = [
  "character",
  "faction",
  "item",
  "world_rule",
  "timeline",
  "chronicle",
  "outline",
  "foreshadowing",
  "inspiration",
];

/**
 * 这一章的台账：写这一章时用到、新造了哪些设定（novel_chapter_ref，由 writer 落库）。
 * 改设定时"哪些章会受波及"就是反查它算出来的，所以前端也按这条线展示。
 *
 * 一条一条平铺太长，按类型（人物 / 物品 / 大纲……）分组摆；一类的名字整段给出、换行铺满，
 * 不做省略 —— 大纲、伏笔这类，名字本身就是内容，截了用户就看不到具体写了什么。
 */
export default function LedgerModal({ threadId, chapter, onClose }: LedgerModalProps) {
  const url =
    threadId && chapter
      ? `/api/novel/method/chapter/ledger?threadId=${encodeURIComponent(threadId)}` +
        `&chapterId=${encodeURIComponent(chapter.id)}`
      : null;
  const { data, loading, error } = useNovelQuery<LedgerResponse>(url);

  const refs = data?.refs ?? [];

  const groups = useMemo(() => {
    const byType = new Map<string, { label: string; refs: LedgerRef[] }>();
    for (const ref of refs) {
      let group = byType.get(ref.refType);
      if (!group) {
        group = { label: ref.refTypeLabel || ref.refType, refs: [] };
        byType.set(ref.refType, group);
      }
      group.refs.push(ref);
    }
    const rank = (type: string) => {
      const index = TYPE_ORDER.indexOf(type);
      return index < 0 ? TYPE_ORDER.length : index;
    };
    return [...byType.entries()]
      .map(([type, group]) => ({ type, ...group }))
      .sort((a, b) => rank(a.type) - rank(b.type));
  }, [refs]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  if (!chapter) return null;

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
            <div className={styles.groups}>
              {groups.map((group) => (
                <section key={group.type} className={styles.group}>
                  <div className={styles.groupHead}>
                    <span className={styles.groupName}>{group.label}</span>
                    <span className={styles.groupCount}>{group.refs.length}</span>
                  </div>
                  <ul className={styles.list}>
                    {group.refs.map((ref) => (
                      <li key={`${ref.refType}-${ref.refId}`} className={styles.item}>
                        <ProfileOutlined className={styles.itemIcon} />
                        <span className={styles.name}>
                          {ref.name || "（已不存在的对象）"}
                        </span>
                        {ref.roleLabel ? (
                          <span className={styles.role}>{ref.roleLabel}</span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
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