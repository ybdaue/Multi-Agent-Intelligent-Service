"use client";

import { useState } from "react";
import {
  BookOutlined,
  DeleteOutlined,
  EditOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import EditableTitle from "../EditableTitle";
import type { Novel } from "../types";
import styles from "./index.module.scss";

interface NovelSidebarProps {
  novels: Novel[];
  activeNovelId: string | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSelectNovel: (id: string) => void;
  onCreateNovel: () => void;
  onRenameNovel: (id: string, title: string) => void;
  onDeleteNovel: (novel: Novel) => void;
}

export default function NovelSidebar({
  novels,
  activeNovelId,
  collapsed,
  onToggleCollapse,
  onSelectNovel,
  onCreateNovel,
  onRenameNovel,
  onDeleteNovel,
}: NovelSidebarProps) {
  const [editingId, setEditingId] = useState<string | null>(null);

  // 只在仍指向自己时清除，避免重命名 A 时的失焦把刚切到 B 的编辑态一并关掉
  const stopEditing = (id: string) => {
    setEditingId((prev) => (prev === id ? null : prev));
  };

  return (
    <aside className={`${styles.sidebar} ${collapsed ? styles.collapsed : ""}`}>
      <div className={styles.header}>
        <button
          type="button"
          className={styles.toggleBtn}
          onClick={onToggleCollapse}
          title={collapsed ? "展开小说列表" : "收起小说列表"}
          aria-label={collapsed ? "展开小说列表" : "收起小说列表"}
        >
          {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        </button>
        {!collapsed && <span className={styles.brandName}>AI 小说创作</span>}
      </div>

      <button
        type="button"
        className={styles.newBtn}
        onClick={onCreateNovel}
        title="新建小说"
      >
        <PlusOutlined />
        {!collapsed && <span>新建小说</span>}
      </button>

      <div className={styles.novelList}>
        {novels.length === 0 ? (
          <div className={styles.empty}>暂无小说</div>
        ) : (
          novels.map((novel) => {
            const active = novel.id === activeNovelId;
            return (
              <div
                key={novel.id}
                className={`${styles.novelItem} ${active ? styles.active : ""}`}
                title={collapsed ? novel.title : undefined}
                onClick={() => onSelectNovel(novel.id)}
              >
                <BookOutlined className={styles.itemIcon} />
                {!collapsed && (
                  <>
                    <EditableTitle
                      value={novel.title}
                      editing={editingId === novel.id}
                      className={styles.itemTitle}
                      onCommit={(next) => {
                        onRenameNovel(novel.id, next);
                        stopEditing(novel.id);
                      }}
                      onCancel={() => stopEditing(novel.id)}
                    />
                    <button
                      type="button"
                      className={styles.actionBtn}
                      title="重命名小说"
                      aria-label="重命名小说"
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditingId(novel.id);
                      }}
                    >
                      <EditOutlined />
                    </button>
                    <button
                      type="button"
                      className={styles.actionBtn}
                      title="删除小说"
                      aria-label="删除小说"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteNovel(novel);
                      }}
                    >
                      <DeleteOutlined />
                    </button>
                  </>
                )}
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
