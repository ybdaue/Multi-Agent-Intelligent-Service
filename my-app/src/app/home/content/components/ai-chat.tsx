"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useEffect, useRef, useState } from "react";
import styles from "../content.module.scss";

const STORAGE_KEY = "content-chat-messages";

function loadMessages() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? JSON.parse(saved) : [];
  } catch {
    return [];
  }
}

export default function AIChat() {
  const [input, setInput] = useState("");
  const [mounted, setMounted] = useState(false);

  const { messages, sendMessage, status, error, setMessages } = useChat({
    transport: new DefaultChatTransport({ api: "/api/chat" }),
    messages: loadMessages(),
  });

  const isLoading = status === "submitted" || status === "streaming";

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (mounted) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    }
  }, [messages, mounted]);

  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "instant" });
  }, [messages, isLoading]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || isLoading) return;
    sendMessage({ text: input });
    setInput("");
  }

  function handleNewChat() {
    localStorage.removeItem(STORAGE_KEY);
    setMessages([]);
  }

  return (
    <div className={styles.chatContainer}>
      <div className={styles.toolbar}>
        <span style={{ fontSize: "0.85rem", color: "var(--color-text-tertiary)" }}>
          {messages.length > 0
            ? `共 ${messages.filter((m) => m.role !== "system").length} 条消息`
            : "DeepSeek AI 助手"}
        </span>
        {messages.length > 0 && (
          <button className={styles.newChatBtn} onClick={handleNewChat}>
            新对话
          </button>
        )}
      </div>

      <div className={styles.messageList}>
        {messages.length === 0 && (
          <div className={styles.emptyState}>
            <div className={styles.emptyIcon}>AI</div>
            <div className={styles.emptyHint}>输入问题，开始与 AI 对话</div>
          </div>
        )}

        {messages
          .filter((m) => m.role !== "system")
          .map((m) => (
            <div
              key={m.id}
              className={`${styles.message} ${m.role === "user" ? styles.messageUser : styles.messageAssistant}`}
            >
              <div
                className={`${styles.avatar} ${m.role === "user" ? styles.avatarUser : styles.avatarAssistant}`}
              >
                {m.role === "user" ? "U" : "AI"}
              </div>
              <div
                className={`${styles.bubble} ${m.role === "user" ? styles.bubbleUser : styles.bubbleAssistant}`}
              >
                {m.parts.filter((p) => p.type === "text").map((p) => p.text).join("")}
              </div>
            </div>
          ))}

        {error && (
          <div className={`${styles.message} ${styles.messageAssistant}`}>
            <div className={`${styles.avatar} ${styles.avatarAssistant}`}>AI</div>
            <div className={`${styles.bubble} ${styles.errorBubble}`}>
              请求失败，请检查网络或 API Key 配置
            </div>
          </div>
        )}

        {isLoading && messages[messages.length - 1]?.role === "user" && (
          <div className={`${styles.message} ${styles.messageAssistant}`}>
            <div className={`${styles.avatar} ${styles.avatarAssistant}`}>AI</div>
            <div className={styles.thinking}>
              <div className={styles.loadingDots}>
                <span />
                <span />
                <span />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={handleSubmit} className={styles.inputArea}>
        <input
          className={styles.input}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入消息..."
          disabled={isLoading}
        />
        <button className={styles.sendButton} type="submit" disabled={isLoading || !input.trim()}>
          {isLoading ? "生成中" : "发送"}
        </button>
      </form>
    </div>
  );
}
