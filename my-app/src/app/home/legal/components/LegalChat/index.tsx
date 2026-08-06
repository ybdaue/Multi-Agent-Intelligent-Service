"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createParser } from "eventsource-parser";
import SessionSidebar from "../SessionSidebar";
import ChatArea from "../ChatArea";
import ChatInput from "../ChatInput";
import type { Attachment, ChatSession, Message } from "../types";
import styles from "./index.module.scss";

const STORAGE_KEY = "ai-legal-sessions";
const WELCOME =
  "您好！我是您的 AI 法律助手。您可以咨询法律问题、上传合同等文档让我分析，或让我代写法律文书。";
const SUGGESTIONS = [
  "帮我写一份劳动合同",
  "合同条款有哪些常见风险？",
  "如何申请劳动仲裁？",
  "欠条怎么写才有法律效力？",
];

function createId() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function emptySession(): ChatSession {
  const now = Date.now();
  return {
    id: createId(),
    threadId: createId(),
    title: "新会话",
    messages: [
      { id: createId(), role: "assistant", content: WELCOME, createdAt: now },
    ],
    createdAt: now,
    updatedAt: now,
  };
}

function loadSessions(): ChatSession[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatSession[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export default function LegalChat() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [loading, setLoading] = useState(false);
  const [streamDone, setStreamDone] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const activeSession =
    sessions.find((s) => s.id === activeSessionId) ?? null;

  // 挂载后（水合完成）从 localStorage 恢复历史会话：
  // 初始 state 恒为空数组，保证服务端渲染与客户端首次渲染一致，避免水合错误
  useEffect(() => {
    setSessions(loadSessions());
    setHydrated(true);
  }, []);

  // 会话持久化到 localStorage（恢复完成前不写入，避免覆盖已有历史）
  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
    } catch {
      // 存储不可用时忽略
    }
  }, [sessions, hydrated]);

  const updateSession = useCallback(
    (id: string, updater: (s: ChatSession) => ChatSession) => {
      setSessions((prev) => prev.map((s) => (s.id === id ? updater(s) : s)));
    },
    [],
  );

  /** 新建会话 */
  const handleNewSession = useCallback(() => {
    const session = emptySession();
    setSessions((prev) => [session, ...prev]);
    setActiveSessionId(session.id);
    setInput("");
    setAttachments([]);
    setLoading(false);
    abortRef.current?.abort();
  }, []);

  /** 切换历史会话 */
  const handleSelectSession = useCallback((id: string) => {
    setActiveSessionId(id);
    setInput("");
    setAttachments([]);
    setLoading(false);
    abortRef.current?.abort();
  }, []);

  /** 删除会话：删除当前会话后自动选中最近一条，若无则新建 */
  const handleDeleteSession = useCallback(
    (id: string) => {
      const remaining = sessions.filter((s) => s.id !== id);
      if (activeSessionId !== id) {
        setSessions(remaining);
        return;
      }
      if (remaining.length > 0) {
        const sorted = [...remaining].sort(
          (a, b) => b.updatedAt - a.updatedAt,
        );
        setSessions(remaining);
        setActiveSessionId(sorted[0].id);
      } else {
        const fresh = emptySession();
        setSessions([fresh]);
        setActiveSessionId(fresh.id);
      }
      setAttachments([]);
      setLoading(false);
      abortRef.current?.abort();
    },
    [activeSessionId, sessions],
  );

  /** 添加附件：当前限制最多一个文件，重复选择会替换已有文件 */
  const handleAddAttachment = useCallback((file: File) => {
    setAttachments([
      {
        id: createId(),
        name: file.name,
        size: file.size,
        type: file.type,
        file,
      },
    ]);
  }, []);

  /** 移除附件 */
  const handleRemoveAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }, []);

  /** 点击建议问题：填入输入框 */
  const handleUseSuggestion = useCallback((text: string) => {
    setInput(text);
  }, []);

  /**
   * 调用 AI 后端接口。
   * 实际请求封装在 /api/legal/askAgent（该服务器路由内部完成用户身份校验，
   * 校验通过后才转发到后端 /multiAgent），这里负责构造 multipart 表单并解析 SSE 流。
   */
  const sendToAssistant = useCallback(
    async (sessionId: string, userMsg: Message, threadId: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);
      setStreamDone(false);

      const assistantMsg: Message = {
        id: createId(),
        role: "assistant",
        content: "",
        createdAt: Date.now(),
      };
      updateSession(sessionId, (s) => ({
        ...s,
        messages: [...s.messages, assistantMsg],
        updatedAt: Date.now(),
      }));

      const appendContent = (patch: string) => {
        updateSession(sessionId, (s) => ({
          ...s,
          messages: s.messages.map((m) =>
            m.id === assistantMsg.id ? { ...m, content: m.content + patch } : m,
          ),
          updatedAt: Date.now(),
        }));
      };

      const setFileInfo = (fileInfo: { filename: string }) => {
        updateSession(sessionId, (s) => ({
          ...s,
          messages: s.messages.map((m) =>
            m.id === assistantMsg.id ? { ...m, fileInfo } : m,
          ),
          updatedAt: Date.now(),
        }));
      };

      try {
        const form = new FormData();
        form.append("threadId", threadId);
        form.append("text", userMsg.content);
        const file = userMsg.attachments?.[0]?.file;
        if (file) {
          form.append("file", file, file.name);
        }

        const res = await fetch("/api/legal/askAgent", {
          method: "POST",
          body: form,
          signal: controller.signal,
        });

        if (!res.ok) {
          const body = await res.json().catch(() => null);
          appendContent(`\n\n[错误] ${body?.error ?? `请求失败 (${res.status})`}`);
          return;
        }
        if (!res.body) {
          appendContent("\n\n[错误] 响应无数据");
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        const parser = createParser({
          onEvent: (event) => {
            try {
              const data = JSON.parse(event.data);
              if (event.event === "token" && typeof data.text === "string") {
                appendContent(data.text);
              } else if (event.event === "file_generated" && data.filename) {
                setFileInfo({ filename: data.filename });
              } else if (event.event === "done") {
                setStreamDone(true);
              } else if (event.event === "error") {
                appendContent(`\n\n[错误] ${data.message ?? "服务异常"}`);
              }
            } catch {
              // 忽略无法解析的事件
            }
          },
        });

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          parser.feed(decoder.decode(value, { stream: true }));
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        console.error("Legal agent stream error:", err);
        appendContent("\n\n[错误] 无法连接 AI 服务");
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        setLoading(false);
      }
    },
    [updateSession],
  );

  /** 发送消息：先写入用户消息，再调用 AI 接口 */
  const handleSendMessage = useCallback(() => {
    const text = input.trim();
    if ((!text && attachments.length === 0) || loading) return;

    // 没有活动会话时自动新建一个
    let sessionId = activeSessionId;
    let threadId: string;
    if (!sessionId) {
      const fresh = emptySession();
      setSessions((prev) => [fresh, ...prev]);
      setActiveSessionId(fresh.id);
      sessionId = fresh.id;
      threadId = fresh.threadId;
    } else {
      const current = sessions.find((s) => s.id === sessionId);
      threadId = current?.threadId ?? createId();
      // 兼容早期 localStorage 里没有 threadId 的会话
      if (!current?.threadId) {
        updateSession(sessionId, (s) => ({ ...s, threadId }));
      }
    }

    const userMsg: Message = {
      id: createId(),
      role: "user",
      content: text,
      attachments: attachments.length > 0 ? [...attachments] : undefined,
      createdAt: Date.now(),
    };

    updateSession(sessionId, (s) => {
      // 取用户第一条消息作为会话标题
      const title =
        s.messages.length <= 1 && text
          ? text.slice(0, 20)
          : s.title;
      return {
        ...s,
        title,
        messages: [...s.messages, userMsg],
        updatedAt: Date.now(),
      };
    });

    setInput("");
    setAttachments([]);
    sendToAssistant(sessionId, userMsg, threadId);
  }, [activeSessionId, attachments, input, loading, sendToAssistant, updateSession, sessions]);

  return (
    <div className={styles.shell}>
      <SessionSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onNewSession={handleNewSession}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
      />
      <main className={styles.main}>
        <ChatArea
          messages={activeSession?.messages ?? []}
          loading={loading}
          streamDone={streamDone}
          suggestions={SUGGESTIONS}
          onUseSuggestion={handleUseSuggestion}
        />
        <ChatInput
          value={input}
          onChange={setInput}
          onSend={handleSendMessage}
          attachments={attachments}
          onAddAttachment={handleAddAttachment}
          onRemoveAttachment={handleRemoveAttachment}
          loading={loading}
        />
      </main>
    </div>
  );
}
