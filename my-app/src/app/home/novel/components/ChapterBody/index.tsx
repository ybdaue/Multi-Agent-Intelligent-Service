"use client";

import { useEffect, useRef } from "react";
import AiPanel from "../AiPanel";
import ChapterStatusSelect from "../ChapterStatusSelect";
import {
  CHAPTER_STATUS_LABEL,
  type Chapter,
  type ChapterStatus,
  type InspirationItem,
  type Message,
  type RunChapter,
} from "../types";
import styles from "./index.module.scss";

interface ChapterBodyProps {
  chapter: Chapter;
  onContentChange: (content: string) => void;
  onChangeStatus: (status: ChapterStatus) => void;
  messages: Message[];
  onSend: (text: string, attachments: InspirationItem[]) => void;
  /** 正在流式生成的那一稿；非空时正文区换成一个临时框，盖住这一章原有的内容 */
  draft: { content: string; streaming: boolean } | null;
  stage: string;
  /** 对话面板整个封掉：本轮还没跑完，或本轮在别的章上跑 */
  chatDisabled: boolean;
  pendingQuestion: boolean;
  /** 本轮正在生成的那一章；和当前章是同一章时由标题旁那个徽章自己标 */
  runChapter: RunChapter | null;
}

export default function ChapterBody({
  chapter,
  onContentChange,
  onChangeStatus,
  messages,
  onSend,
  draft,
  stage,
  chatDisabled,
  pendingQuestion,
  runChapter,
}: ChapterBodyProps) {
  // 定稿了才只读；草稿与待修复都要能直接改正文
  const done = chapter.status === "done";
  const temp = chapter.temp === true;
  const paragraphs = chapter.content.split("\n").filter((p) => p.trim());
  const draftParagraphs = draft?.content.split("\n").filter((p) => p.trim()) ?? [];
  const scrollRef = useRef<HTMLDivElement>(null);

  // 本轮写在别的章上：那一章照常在写，这一章该显示什么显示什么，只在标题栏右边挂一句提示
  const runningElsewhere = runChapter && runChapter.id !== chapter.id ? runChapter : null;

  // 流式正文越写越长，跟着滚到底
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [draft?.content]);

  return (
    <div className={styles.body}>
      <div className={styles.textPanel}>
        <div className={styles.textHeader}>
          <span className={styles.title}>{chapter.title}</span>
          {draft ? (
            <span className={`${styles.badge} ${styles.generating}`}>
              {draft.streaming ? "生成中…" : "待确认"}
            </span>
          ) : temp ? (
            // 还没落库：状态不存在库里，所以只报"临时"，也不给改
            <span className={`${styles.badge} ${styles.temp}`}>临时</span>
          ) : (
            <>
              <span className={`${styles.badge} ${styles[chapter.status]}`}>
                {CHAPTER_STATUS_LABEL[chapter.status]}
              </span>
              <ChapterStatusSelect value={chapter.status} onChange={onChangeStatus} />
            </>
          )}
          {/* 本轮在别的章上写：这一章照常看，只在最右边报一句写的是哪一章 */}
          {runningElsewhere && (
            <span className={styles.runHint}>
              {runningElsewhere.pending ? "待确认" : "正在生成"} {runningElsewhere.title}
            </span>
          )}
        </div>

        {draft ? (
          // 临时框：writer / editor 交的正文逐字长出来，还不属于这一章 ——
          // 要等用户在对话框里确认、update 落库、重拉列表之后，chapter 才真的变。
          <div ref={scrollRef} className={styles.readonly}>
            {draftParagraphs.length === 0 ? (
              <p className={styles.placeholder}>AI 正在写作…</p>
            ) : (
              draftParagraphs.map((p, i) => <p key={i}>{p}</p>)
            )}
          </div>
        ) : done ? (
          <div className={styles.readonly}>
            {paragraphs.length === 0 ? (
              <p className={styles.placeholder}>本章暂无正文</p>
            ) : (
              paragraphs.map((p, i) => <p key={i}>{p}</p>)
            )}
          </div>
        ) : (
          <textarea
            className={styles.editor}
            value={chapter.content}
            placeholder="在此输入本章正文…"
            onChange={(e) => onContentChange(e.target.value)}
          />
        )}
      </div>

      {/* 按章节 key 重挂载，切章时输入框与滚动位置一并重置 */}
      <AiPanel
        key={chapter.id}
        messages={messages}
        onSend={onSend}
        stage={stage}
        disabled={chatDisabled}
        pendingQuestion={pendingQuestion}
      />
    </div>
  );
}
