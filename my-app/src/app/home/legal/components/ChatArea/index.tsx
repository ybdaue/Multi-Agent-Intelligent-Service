"use client";

import { useEffect, useRef } from "react";
import {
  RobotOutlined,
  UserOutlined,
  FileTextOutlined,
  DownloadOutlined,
} from "@ant-design/icons";
import type { Message } from "../types";
import styles from "./index.module.scss";

interface ChatAreaProps {
  messages: Message[];
  loading: boolean;
  streamDone: boolean;
  suggestions?: string[];
  onUseSuggestion?: (text: string) => void;
}

export default function ChatArea({
  messages,
  loading,
  streamDone,
  suggestions = [],
  onUseSuggestion,
}: ChatAreaProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (loading) {
      // 流式输出期间瞬时钉在底部，避免平滑滚动被高频 token 更新打断
      el.scrollTop = el.scrollHeight;
    } else {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [messages, loading]);

  if (messages.length === 0) {
    return (
      <div className={styles.chatArea}>
        <div className={styles.emptyState}>
          <div className={styles.avatar}>
            <RobotOutlined />
          </div>
          <h2 className={styles.emptyTitle}>您好，我是 AI 法律助手</h2>
          <p className={styles.emptyDesc}>
            可以为您提供法律咨询、合同分析、文书代写等服务
          </p>
          {suggestions.length > 0 && (
            <div className={styles.suggestions}>
              {suggestions.map((s) => (
                <button
                  key={s}
                  className={styles.suggestion}
                  onClick={() => onUseSuggestion?.(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  const lastId = messages.length > 0 ? messages[messages.length - 1].id : null;

  return (
    <div ref={scrollRef} className={styles.chatArea}>
      <div className={styles.messageList}>
        {messages.map((m) => {
          // 流式进行中，最后一条空助手消息即为正在生成的回答，气泡内显示打字指示
          const isStreaming =
            m.role === "assistant" && loading && m.id === lastId && !m.content;
          // 最后一条助手消息已有内容但仍在 loading（子 agent 工具调用中），在文末显示加载动画
          const isStillWorking =
            m.role === "assistant" && loading && m.id === lastId && !!m.content;
          const isEmptyAssistant =
            m.role === "assistant" &&
            !m.content &&
            !(m.attachments && m.attachments.length > 0);
          // 空助手消息仅在作为流式占位时渲染，避免多余的空气泡
          if (isEmptyAssistant && !isStreaming) return null;
          return (
            <div key={m.id} className={`${styles.messageRow} ${styles[m.role]}`}>
              <div className={styles.avatarWrap}>
                {m.role === "assistant" ? <RobotOutlined /> : <UserOutlined />}
              </div>
              <div className={styles.bubbleWrap}>
                {m.attachments && m.attachments.length > 0 && (
                  <div className={styles.attachments}>
                    {m.attachments.map((a) => (
                      <div key={a.id} className={styles.attachmentChip}>
                        <FileTextOutlined />
                        <span>{a.name}</span>
                      </div>
                    ))}
                  </div>
                )}
                {isStreaming ? (
                  <div className={`${styles.bubble} ${styles.typing}`}>
                    <span className={styles.dot} />
                    <span className={styles.dot} />
                    <span className={styles.dot} />
                  </div>
                ) : m.content ? (
                  <div className={styles.bubble}>
                    {m.content}
                    {isStillWorking && (
                      <span className={styles.typingInline}>
                        <span className={styles.dot} />
                        <span className={styles.dot} />
                        <span className={styles.dot} />
                      </span>
                    )}
                  </div>
                ) : null}
                {m.fileInfo && (m.id !== lastId || streamDone) && (
                  <a
                    className={styles.downloadChip}
                    href={`/api/legal/download?filename=${encodeURIComponent(m.fileInfo.filename)}`}
                    download={m.fileInfo.filename}
                  >
                    <DownloadOutlined />
                    <span>{m.fileInfo.filename}</span>
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
