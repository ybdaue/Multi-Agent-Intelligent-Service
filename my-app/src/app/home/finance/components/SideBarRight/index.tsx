"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import styles from "./index.module.scss";

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface FinanceSidebarProps {
  messages: Message[];
  onSendMessage: (message: string) => Promise<void>;
  onNewChat?: () => void;
  loading: boolean;
}

export default function FinanceSidebar({ messages, onSendMessage, onNewChat, loading }: FinanceSidebarProps) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [toggleTop, setToggleTop] = useState(12);
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ startY: number; startTop: number } | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { startY: e.clientY, startTop: toggleTop };

    const handleMouseMove = (e: MouseEvent) => {
      if (!dragRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const maxTop = rect.height - 40;
      const newTop = Math.max(0, Math.min(maxTop, dragRef.current.startTop + (e.clientY - dragRef.current.startY)));
      setToggleTop(newTop);
    };

    const handleMouseUp = (e: MouseEvent) => {
      if (dragRef.current) {
        const dy = Math.abs(e.clientY - dragRef.current.startY);
        if (dy < 5) {
          setOpen((o) => !o);
        }
      }
      dragRef.current = null;
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  }, [toggleTop]);

  const handleChatSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;
    const msg = input.trim();
    setInput("");
    await onSendMessage(msg);
  };

  return (
    <div className={styles.wrapper} ref={containerRef}>
      {!open && (
        <button
          className={styles.toggle}
          style={{ top: toggleTop }}
          onMouseDown={handleMouseDown}
          title="打开 AI 助手"
        >
          AI
        </button>
      )}

      <div className={`${styles.sidebar} ${open ? styles.open : ""}`}>
        <div className={styles.header}>
          <span>AI 股票分析</span>
          <div className={styles.headerActions}>
            <button onClick={onNewChat} className={styles.newChatBtn}>新建对话</button>
            <button onClick={() => setOpen(false)}>x</button>
          </div>
        </div>

        <div className={styles.messages}>
          {messages.map((msg, i) => (
            <div key={`msg-${i}`} className={`${styles.bubble} ${styles[msg.role]}`}>
              {msg.content.split("\n").map((line, j) => (
                <p key={`line-${i}-${j}`}>{line}</p>
              ))}
            </div>
          ))}
          {loading && (
            <div className={`${styles.bubble} ${styles.assistant}`}>
              <p>分析中...</p>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <form className={styles.inputArea} onSubmit={handleChatSubmit}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="询问关于股票的问题..."
            disabled={loading}
          />
          <button type="submit" disabled={loading || !input.trim()}>
            发送
          </button>
        </form>
      </div>
    </div>
  );
}
