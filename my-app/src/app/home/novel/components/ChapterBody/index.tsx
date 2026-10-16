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
  /** 正文有没有没保存的改动（决定保存按钮亮不亮） */
  dirty: boolean;
  /** 这一章能不能手改（临时章 / 生成中 / 已定稿都不能） */
  canEdit: boolean;
  /** 不能改的原因，按钮置灰时当 title 提示；空串 = 能改 */
  editBlockReason: string;
  /** 保存按钮转圈：这一章正落着一轮 */
  saving: boolean;
  /** 点保存：把改后正文交给图里（重报台账、定级、审稿、入库确认） */
  onSave: () => void;
  messages: Message[];
  onSend: (text: string, attachments: InspirationItem[]) => void;
  /** 这本书的 id（= threadId）：透给 AiPanel，从灵感库挑灵感时要用 */
  threadId: string | null;
  /** 正在流式生成的那一稿；非空时正文区换成一个临时框，盖住这一章原有的内容 */
  draft: { content: string; streaming: boolean } | null;
  stage: string;
  /** 对话面板整个封掉：本轮还没跑完，或本轮在别的章上跑 */
  chatDisabled: boolean;
  /** 这一轮的流还开着（能掐断） */
  running: boolean;
  onStop: () => void;
  pendingQuestion: boolean;
  /** 停在确认上时后端给的出口按钮（收下 / 按库里改） */
  answerOptions: { id: string; label: string }[];
  onAnswer: (option: { id: string; label: string }) => void;
  /** 清空这本的对话记录（后端那份一起清） */
  onClear: () => void;
  /** 本轮正在生成的那一章；和当前章是同一章时由标题旁那个徽章自己标 */
  runChapter: RunChapter | null;
  /** 这本书的 AI 审稿开关（挂在右侧对话面板顶部） */
  reviewEnabled: boolean;
  onToggleReview: (on: boolean) => void;
}

export default function ChapterBody({
  chapter,
  onContentChange,
  onChangeStatus,
  dirty,
  canEdit,
  editBlockReason,
  saving,
  onSave,
  messages,
  onSend,
  threadId,
  draft,
  stage,
  chatDisabled,
  running,
  onStop,
  pendingQuestion,
  answerOptions,
  onAnswer,
  onClear,
  runChapter,
  reviewEnabled,
  onToggleReview,
}: ChapterBodyProps) {
  // 定稿了才只读；草稿与待修复都要能直接改正文
  const done = chapter.status === "done";
  const temp = chapter.temp === true;
  const paragraphs = chapter.content.split("\n").filter((p) => p.trim());
  const draftParagraphs = draft?.content.split("\n").filter((p) => p.trim()) ?? [];
  const scrollRef = useRef<HTMLDivElement>(null);

  // 本轮写在别的章上：那一章照常在写，这一章该显示什么显示什么，只在标题栏右边挂一句提示
  const runningElsewhere = runChapter && runChapter.id !== chapter.id ? runChapter : null;

  // 保存按钮的悬停说明：能改时解释按钮为何还灰着，不能改时给出原因
  const saveHint = canEdit ? (dirty ? "保存这一章的改动" : "正文没有改动") : editBlockReason;

  // 流式正文越写越长，跟着滚到底；切到正在生成的章时也滚到底
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [draft?.content, chapter.id]);

  return (
    <div className={styles.body}>
      {/* 按章节 key 重挂载：切章时正文滚动条回到最顶上（复用 DOM 会让位置留着）。
          旁边的 AiPanel 也用 chapter.id 当 key，两兄弟撞 key，所以这里加前缀错开。 */}
      <div key={`text-${chapter.id}`} className={styles.textPanel}>
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
          {/* 右端一组：本轮在别的章上写的那句提示 + 保存按钮 */}
          <div className={styles.headerRight}>
            {runningElsewhere && (
              <span className={styles.runHint}>
                {runningElsewhere.pending ? "待确认" : "正在生成"} {runningElsewhere.title}
              </span>
            )}
            {/* 临时章 / 定稿章也挂着这个按钮，只是置灰 + title 说明原因 */}
            {!draft && (
              <span className={styles.saveWrap} title={saveHint}>
                <button
                  type="button"
                  className={`${styles.saveBtn} ${dirty && canEdit ? styles.saveBtnActive : ""}`}
                  disabled={!canEdit || !dirty || saving}
                  onClick={onSave}
                >
                  {saving ? "保存中…" : "保存"}
                </button>
              </span>
            )}
          </div>
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
        threadId={threadId}
        stage={stage}
        disabled={chatDisabled}
        running={running}
        onStop={onStop}
        pendingQuestion={pendingQuestion}
        answerOptions={answerOptions}
        onAnswer={onAnswer}
        onClear={onClear}
        reviewEnabled={reviewEnabled}
        onToggleReview={onToggleReview}
      />
    </div>
  );
}
