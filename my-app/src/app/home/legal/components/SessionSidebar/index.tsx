"use client";

import { useMemo } from "react";
import {
  PlusOutlined,
  MessageOutlined,
  DeleteOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import type { ChatSession } from "../types";
import styles from "./index.module.scss";

interface SessionSidebarProps {
  sessions: ChatSession[];
  activeSessionId: string | null;
  onNewSession: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
}

export default function SessionSidebar({
  sessions,
  activeSessionId,
  onNewSession,
  onSelectSession,
  onDeleteSession,
}: SessionSidebarProps) {
  const sorted = useMemo(
    () => [...sessions].sort((a, b) => b.updatedAt - a.updatedAt),
    [sessions],
  );

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

      <div className={styles.sessionList}>
        <div className={styles.sectionLabel}>历史会话</div>
        {sorted.length === 0 ? (
          <div className={styles.empty}>暂无历史会话</div>
        ) : (
          sorted.map((session) => {
            const active = session.id === activeSessionId;
            return (
              <div
                key={session.id}
                className={`${styles.sessionItem} ${active ? styles.active : ""}`}
                onClick={() => onSelectSession(session.id)}
              >
                <MessageOutlined className={styles.itemIcon} />
                <span className={styles.itemTitle}>{session.title}</span>
                <button
                  className={styles.deleteBtn}
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteSession(session.id);
                  }}
                  title="删除会话"
                >
                  <DeleteOutlined />
                </button>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
