"use client";

import { useCallback, useRef } from "react";
import {
  PlusOutlined,
  MessageOutlined,
  RobotOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import type { SessionListItem } from "../types";
import styles from "./index.module.scss";

interface SessionSidebarProps {
  items: SessionListItem[];
  activeThreadId: string | null;
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  error: string | null;
  deletingThreadId: string | null;
  onNewSession: () => void;
  onSelectSession: (item: SessionListItem) => void;
  onDeleteSession: (item: SessionListItem) => void;
  onLoadMore: () => void;
}

export default function SessionSidebar({
  items,
  activeThreadId,
  loading,
  loadingMore,
  hasMore,
  error,
  deletingThreadId,
  onNewSession,
  onSelectSession,
  onDeleteSession,
  onLoadMore,
}: SessionSidebarProps) {
  const listRef = useRef<HTMLDivElement>(null);

  // 触底（预留 24px）自动加载下一页
  const handleScroll = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 24) {
      onLoadMore();
    }
  }, [onLoadMore]);

  return (
    <aside className={styles.sidebar}>
      <div className={styles.header}>
        <div className={styles.brand}>
          <RobotOutlined className={styles.brandIcon} />
          <span className={styles.brandName}>AI 法律服务</span>
        </div>
        <button className={styles.newBtn} onClick={onNewSession}>
          <PlusOutlined />
          <span>新会话</span>
        </button>
      </div>

      <div ref={listRef} className={styles.sessionList} onScroll={handleScroll}>
        <div className={styles.sectionLabel}>历史会话</div>

        {loading ? (
          <div className={styles.hint}>正在加载历史会话…</div>
        ) : error && items.length === 0 ? (
          <div className={styles.hint}>{error}</div>
        ) : items.length === 0 ? (
          <div className={styles.empty}>暂无历史会话</div>
        ) : (
          <>
            {items.map((item) => {
              const active = item.threadId === activeThreadId;
              return (
                <div
                  key={item.threadId}
                  className={`${styles.sessionItem} ${active ? styles.active : ""}`}
                  onClick={() => onSelectSession(item)}
                >
                  <MessageOutlined className={styles.itemIcon} />
                  <span className={styles.itemTitle}>{item.title}</span>
                  <button
                    type="button"
                    className={styles.deleteBtn}
                    title="删除会话"
                    aria-label="删除会话"
                    disabled={deletingThreadId === item.threadId}
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteSession(item);
                    }}
                  >
                    <DeleteOutlined />
                  </button>
                </div>
              );
            })}
            {loadingMore && <div className={styles.hint}>加载更多…</div>}
            {!hasMore && !loadingMore && (
              <div className={styles.hint}>没有更多会话了</div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
