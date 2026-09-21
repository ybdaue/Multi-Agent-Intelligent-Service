"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  RobotOutlined,
  UserOutlined,
  FileTextOutlined,
  DownloadOutlined,
  CopyOutlined,
  CheckOutlined,
} from "@ant-design/icons";
import type { Message } from "../types";
import styles from "./index.module.scss";

/** 复制文本到剪贴板，返回是否成功。
 * 优先 Clipboard API；它只在安全上下文存在，用 http 访问非 localhost 时整个
 * navigator.clipboard 是 undefined，此时退回 execCommand（已废弃但仍普遍可用）。
 */
async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // 权限被拒等，继续走下面的兜底
    }
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

interface ChatAreaProps {
  messages: Message[];
  loading: boolean;
  historyLoading?: boolean;
  streamDone: boolean;
  suggestions?: string[];
  onUseSuggestion?: (text: string) => void;
}

export default function ChatArea({
  messages,
  loading,
  historyLoading = false,
  streamDone,
  suggestions = [],
  onUseSuggestion,
}: ChatAreaProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const copyTimerRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
    },
    [],
  );

  /** 复制消息正文；成功后图标短暂切成对勾做反馈 */
  const handleCopy = useCallback(async (id: string, text: string) => {
    if (!(await copyText(text))) return;
    setCopiedId(id);
    if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
    copyTimerRef.current = window.setTimeout(() => setCopiedId(null), 1500);
  }, []);

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

  if (historyLoading) {
    return (
      <div className={styles.chatArea}>
        <div className={styles.historyLoading}>正在加载历史会话…</div>
      </div>
    );
  }

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
          // 下载条在流式生成期间先不显示；历史消息 loading=false，直接显示
          const fileInfo =
            m.fileInfo && (m.id !== lastId || streamDone || !loading)
              ? m.fileInfo
              : null;
          // 生成中不给复制：正文还在追加
          const canCopy = !!m.content && !isStillWorking;
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
                {/* 下载条与复制图标同一行：下载条靠左、复制图标靠右。整行是气泡的流内
                    兄弟，占位算进这条消息，不会压到下一条 */}
                {(fileInfo || canCopy) && (
                  <div className={styles.bubbleActions}>
                    {fileInfo && (
                      <a
                        className={styles.downloadChip}
                        href={`/api/legal/download?fileId=${encodeURIComponent(fileInfo.fileId)}`}
                        download={fileInfo.filename}
                      >
                        <DownloadOutlined />
                        <span>{fileInfo.filename}</span>
                      </a>
                    )}
                    {canCopy && (
                      <button
                        type="button"
                        className={styles.copyBtn}
                        onClick={() => void handleCopy(m.id, m.content)}
                        title={copiedId === m.id ? "已复制" : "复制"}
                        aria-label={copiedId === m.id ? "已复制" : "复制"}
                      >
                        {copiedId === m.id ? <CheckOutlined /> : <CopyOutlined />}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
