"use client";

import { useState } from "react";
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  ExclamationCircleOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  ProfileOutlined,
} from "@ant-design/icons";
import ChapterStatusSelect from "../ChapterStatusSelect";
import EditableTitle from "../EditableTitle";
import {
  CHAPTER_STATUS_LABEL,
  type Chapter,
  type ChapterStatus,
  type Novel,
} from "../types";
import styles from "./index.module.scss";

/** 一档一个图标一种颜色：完成绿、草稿黄、待修复红 */
const STATUS_ICON: Record<ChapterStatus, { Icon: typeof CheckCircleOutlined; cls: string }> = {
  done: { Icon: CheckCircleOutlined, cls: "done" },
  draft: { Icon: ClockCircleOutlined, cls: "draft" },
  fixing: { Icon: ExclamationCircleOutlined, cls: "fixing" },
};

interface ChapterListProps {
  novel: Novel | null;
  activeChapterId: string | null;
  /** 章节栏折起来了：只留章节号 */
  collapsed: boolean;
  onToggleCollapse: () => void;
  /** 展开着才给操作按钮：收起时只保留章节状态标记，隐藏重命名/删除 */
  showActions: boolean;
  /** 已经有一个还没落库的章挡着：不给再建，等它写完、用户确认之后才放行 */
  createBlocked: boolean;
  onSelectChapter: (id: string) => void;
  onCreateChapter: () => void;
  onRenameChapter: (id: string, title: string) => void;
  onDeleteChapter: (chapter: Chapter) => void;
  onChangeStatus: (chapter: Chapter, status: ChapterStatus) => void;
  /** 看这一章的台账：用到、新造了哪些设定 */
  onShowLedger: (chapter: Chapter) => void;
}

/** 章节栏折起来时条目上只留章节号（"第12章 风起" → "第12章"）；完整标题进悬浮提示 */
function shortTitle(title: string) {
  return title.match(/^第\s*\d+\s*章/)?.[0] ?? title;
}

export default function ChapterList({
  novel,
  activeChapterId,
  collapsed,
  onToggleCollapse,
  showActions,
  createBlocked,
  onSelectChapter,
  onCreateChapter,
  onRenameChapter,
  onDeleteChapter,
  onChangeStatus,
  onShowLedger,
}: ChapterListProps) {
  const [editingId, setEditingId] = useState<string | null>(null);

  const stopEditing = (id: string) => {
    setEditingId((prev) => (prev === id ? null : prev));
  };

  return (
    <aside className={`${styles.column} ${collapsed ? styles.collapsed : ""}`}>
      <div className={styles.header}>
        <button
          type="button"
          className={styles.toggleBtn}
          onClick={onToggleCollapse}
          title={collapsed ? "展开章节列表" : "收起章节列表"}
          aria-label={collapsed ? "展开章节列表" : "收起章节列表"}
        >
          {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        </button>
        {!collapsed && (
          <span className={styles.headerTitle} title={novel?.title}>
            {novel?.title ?? "未选择小说"}
          </span>
        )}
      </div>

      <div className={styles.chapterList}>
        {!novel ? (
          <div className={styles.empty}>请先在左侧选择小说</div>
        ) : novel.chapters.length === 0 ? (
          <div className={styles.empty}>暂无章节</div>
        ) : (
          novel.chapters.map((chapter) => {
            const active = chapter.id === activeChapterId;
            // 还没落库的章：状态无处可写，所以只报"临时"，选择按钮也不给
            const temp = chapter.temp === true;
            const { Icon, cls } = STATUS_ICON[chapter.status];
            return (
              <div
                key={chapter.id}
                className={`${styles.chapterItem} ${active ? styles.active : ""}`}
                title={chapter.title}
                onClick={() => onSelectChapter(chapter.id)}
              >
                {!collapsed &&
                  (temp ? (
                    <span className={styles.tempTag}>临时</span>
                  ) : (
                    <Icon
                      className={`${styles.statusIcon} ${styles[cls]}`}
                      title={CHAPTER_STATUS_LABEL[chapter.status]}
                    />
                  ))}
                {showActions && !temp && (
                  <ChapterStatusSelect
                    compact
                    value={chapter.status}
                    onChange={(status) => onChangeStatus(chapter, status)}
                  />
                )}
                <EditableTitle
                  value={chapter.title}
                  displayValue={collapsed ? shortTitle(chapter.title) : undefined}
                  editing={editingId === chapter.id}
                  className={styles.itemTitle}
                  onCommit={(next) => {
                    onRenameChapter(chapter.id, next);
                    stopEditing(chapter.id);
                  }}
                  onCancel={() => stopEditing(chapter.id)}
                />
                {showActions && (
                  <>
                    <button
                      type="button"
                      className={styles.actionBtn}
                      title="查看台账"
                      aria-label="查看台账"
                      onClick={(e) => {
                        e.stopPropagation();
                        onShowLedger(chapter);
                      }}
                    >
                      <ProfileOutlined />
                    </button>
                    <button
                      type="button"
                      className={styles.actionBtn}
                      title="重命名章节"
                      aria-label="重命名章节"
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditingId(chapter.id);
                      }}
                    >
                      <EditOutlined />
                    </button>
                    <button
                      type="button"
                      className={styles.actionBtn}
                      title="删除章节"
                      aria-label="删除章节"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteChapter(chapter);
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

        {/* 紧跟在最后一章下面，不固定在区域底部 */}
        {novel && (
          <button
            type="button"
            className={styles.addBtn}
            onClick={onCreateChapter}
            disabled={createBlocked}
            title={createBlocked ? "上一章还没写完落库，写完并确认后才能再建" : "新建章节"}
            aria-label="新建章节"
          >
            <PlusOutlined />
          </button>
        )}
      </div>
    </aside>
  );
}
