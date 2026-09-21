"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createParser } from "eventsource-parser";
import SessionSidebar from "../SessionSidebar";
import ChatArea from "../ChatArea";
import ChatInput from "../ChatInput";
import type {
  Attachment,
  ChatSession,
  Message,
  SessionHistoryResponse,
  SessionListResponse,
  SessionListItem,
} from "../types";
import styles from "./index.module.scss";

const PAGE_SIZE = 20;
const UNTITLED = "未命名会话";
const SUGGESTIONS = [
  "帮我写一份劳动合同",
  "合同条款有哪些常见风险？",
  "如何申请劳动仲裁？",
  "欠条怎么写才有法律效力？",
];

function createId() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function toTime(value: string): number {
  const t = Date.parse(value);
  return Number.isNaN(t) ? Date.now() : t;
}

function newChat(): ChatSession {
  const now = Date.now();
  return {
    key: createId(),
    threadId: "", // 新会话首条消息不带 threadId，由后端生成权威 id 并经 SSE session 事件回传
    title: "新会话",
    messages: [], // 无消息时 ChatArea 展示空态引导，不注入欢迎气泡
    createdAt: now,
    updatedAt: now,
  };
}

/** 后端 user_session_history 消息 -> 前端 Message（后端未存每条精确时间，按会话起始递增占位）。 */
function mapHistory(data: SessionHistoryResponse): Message[] {
  const base = toTime(data.createdAt);
  return (data.messages ?? []).map((m, i) => ({
    id: m.messageId || `${m.role}-${i}`,
    role: m.role,
    content: m.content ?? "",
    // 历史里带出的生成文书，下载条与实时会话渲染一致
    fileInfo:
      m.fileInfo?.fileId && m.fileInfo.filename ? m.fileInfo : undefined,
    createdAt: base + i,
  }));
}

function dedupeByThread(items: SessionListItem[]): SessionListItem[] {
  const seen = new Set<string>();
  const out: SessionListItem[] = [];
  for (const it of items) {
    if (seen.has(it.threadId)) continue;
    seen.add(it.threadId);
    out.push(it);
  }
  return out;
}

export default function LegalChat() {
  const [active, setActive] = useState<ChatSession | null>(null);
  const [items, setItems] = useState<SessionListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0); // 已加载到的页码（0=尚未加载）
  const [initialLoading, setInitialLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [deletingThreadId, setDeletingThreadId] = useState<string | null>(null);

  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [loading, setLoading] = useState(false);
  const [streamDone, setStreamDone] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const historySeqRef = useRef(0); // 递增使过期历史请求失效
  const autoOpenedRef = useRef(false); // 挂载后只自动打开一次最近会话

  /** 拉取某一页会话列表；mode=replace 重载第 1 页，append 用于触底加载下一页。 */
  const fetchPage = useCallback(
    async (p: number, mode: "replace" | "append") => {
      const params = new URLSearchParams({
        page: String(p),
        pageSize: String(PAGE_SIZE),
      });
      const res = await fetch(`/api/legal/sessions?${params.toString()}`);
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.error ?? `请求失败 (${res.status})`);
      }
      const data = (await res.json()) as SessionListResponse;
      const incoming = (data.sessions ?? []).map((s) => ({
        threadId: s.threadId,
        title: s.title || UNTITLED,
      }));
      setItems((prev) =>
        mode === "append" ? dedupeByThread([...prev, ...incoming]) : incoming,
      );
      setTotal(data.total ?? 0);
      setPage(p);
    },
    [],
  );

  /** 发送完成后刷新第 1 页，让刚持久化的会话按最新排序回到顶部。 */
  const refreshList = useCallback(() => {
    void fetchPage(1, "replace").catch(() => {});
  }, [fetchPage]);

  // 挂载后加载第 1 页历史会话
  useEffect(() => {
    fetchPage(1, "replace")
      .catch((err: Error) => setListError(err.message || "获取历史会话失败"))
      .finally(() => setInitialLoading(false));
  }, [fetchPage]);

  const hasMore = items.length < total;

  /** 触底加载更多 */
  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore || initialLoading) return;
    setLoadingMore(true);
    try {
      await fetchPage(page + 1, "append");
    } catch {
      // 到底 / 网络异常：保留已加载内容，让用户再次触底重试
    } finally {
      setLoadingMore(false);
    }
  }, [fetchPage, hasMore, initialLoading, loadingMore, page]);

  /** 新建会话（仅驻留内存，首条消息发出并被后端持久化后才进入历史列表） */
  const handleNewSession = useCallback(() => {
    abortRef.current?.abort();
    historySeqRef.current += 1; // 使进行中的历史加载失效，避免其回写当前空态会话
    setActive(newChat());
    setInput("");
    setAttachments([]);
    setLoading(false);
    setHistoryLoading(false);
    setStreamDone(false);
  }, []);

  /** 点开历史会话：先拉取对话历史再渲染 */
  const handleSelectSession = useCallback(
    async (item: SessionListItem) => {
      if (active?.threadId === item.threadId) return;
      abortRef.current?.abort();
      const seq = ++historySeqRef.current;
      setInput("");
      setAttachments([]);
      setLoading(false);
      setStreamDone(false);
      setHistoryLoading(true);
      setActive({
        key: createId(),
        threadId: item.threadId,
        title: item.title,
        messages: [],
        createdAt: Date.now(),
        updatedAt: Date.now(),
      });
      try {
        const params = new URLSearchParams({ threadId: item.threadId });
        const res = await fetch(`/api/legal/sessions/history?${params.toString()}`);
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.error ?? `请求失败 (${res.status})`);
        }
        const data = (await res.json()) as SessionHistoryResponse;
        if (seq !== historySeqRef.current) return;
        setActive((prev) =>
          prev && prev.threadId === item.threadId
            ? {
                ...prev,
                title: data.title || prev.title,
                messages: mapHistory(data),
                updatedAt: toTime(data.updatedAt),
              }
            : prev,
        );
      } catch (err) {
        if (seq !== historySeqRef.current) return;
        const msg = err instanceof Error ? err.message : "未知错误";
        setActive((prev) =>
          prev && prev.threadId === item.threadId
            ? {
                ...prev,
                messages: [
                  {
                    id: createId(),
                    role: "assistant",
                    content: `[加载历史失败] ${msg}`,
                    createdAt: Date.now(),
                  },
                ],
              }
            : prev,
        );
      } finally {
        if (seq === historySeqRef.current) setHistoryLoading(false);
      }
    },
    [active?.threadId],
  );

  /** 删除会话：确认后调后端删除（历史+快照），本地移除；删的是当前会话则回到空白新会话 */
  const handleDeleteSession = useCallback(
    async (item: SessionListItem) => {
      if (!window.confirm(`确定删除会话「${item.title}」吗？删除后不可恢复。`)) return;

      // 尚未持久化到后端的本地新会话：仅本地丢弃
      if (!item.threadId) {
        if (active?.threadId === item.threadId) handleNewSession();
        return;
      }

      setDeletingThreadId(item.threadId);
      try {
        const params = new URLSearchParams({ threadId: item.threadId });
        const res = await fetch(`/api/legal/sessions?${params.toString()}`, {
          method: "DELETE",
        });
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.error ?? `请求失败 (${res.status})`);
        }
        setItems((prev) => prev.filter((i) => i.threadId !== item.threadId));
        setTotal((prev) => Math.max(0, prev - 1));
        if (active?.threadId === item.threadId) {
          handleNewSession();
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : "未知错误";
        window.alert(`删除会话失败：${msg}`);
      } finally {
        setDeletingThreadId(null);
      }
    },
    [active?.threadId, handleNewSession],
  );

  // 挂载后若已有历史会话，默认打开最近一个（列表按 updatedAt 倒序，首项即最新）
  useEffect(() => {
    if (autoOpenedRef.current) return;
    if (initialLoading || active || items.length === 0) return;
    autoOpenedRef.current = true;
    void handleSelectSession(items[0]);
  }, [active, handleSelectSession, initialLoading, items]);

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

  const handleRemoveAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const handleUseSuggestion = useCallback((text: string) => {
    setInput(text);
  }, []);

  /** 流式请求 AI；仅当 active 仍是发起时那个会话（按 key）才写入，防止中途切换污染其它会话 */
  const sendToAssistant = useCallback(
    async (sessionKey: string, threadId: string, userMsg: Message) => {
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
      setActive((prev) =>
        prev && prev.key === sessionKey
          ? { ...prev, messages: [...prev.messages, assistantMsg], updatedAt: Date.now() }
          : prev,
      );

      const patch = (fn: (m: Message) => Message) =>
        setActive((prev) =>
          prev && prev.key === sessionKey
            ? {
                ...prev,
                messages: prev.messages.map((m) =>
                  m.id === assistantMsg.id ? fn(m) : m,
                ),
                updatedAt: Date.now(),
              }
            : prev,
        );
      const appendContent = (text: string) =>
        patch((m) => ({ ...m, content: m.content + text }));
      const setFileInfo = (fileInfo: { fileId: string; filename: string }) =>
        patch((m) => ({ ...m, fileInfo }));

      try {
        const form = new FormData();
        if (threadId) {
          form.append("threadId", threadId);
        }
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
              if (
                event.event === "session" &&
                typeof data.threadId === "string" &&
                data.threadId
              ) {
                // 后端生成的权威 threadId：绑定到当前会话（首条消息后即可获知）
                setActive((prev) =>
                  prev && prev.key === sessionKey
                    ? { ...prev, threadId: data.threadId }
                    : prev,
                );
              } else if (event.event === "token" && typeof data.text === "string") {
                appendContent(data.text);
              } else if (
                event.event === "file_generated" &&
                data.fileId &&
                data.filename
              ) {
                setFileInfo({ fileId: data.fileId, filename: data.filename });
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
        // 本轮问答已由后端持久化，刷新第 1 页让该会话按最新排序置顶
        refreshList();
      }
    },
    [refreshList],
  );

  /** 发送消息：写入用户消息后调用 AI 接口；无活动会话时自动新建（threadId 由后端生成回传） */
  const handleSendMessage = useCallback(() => {
    const text = input.trim();
    if ((!text && attachments.length === 0) || loading || historyLoading) return;

    const userMsg: Message = {
      id: createId(),
      role: "user",
      content: text,
      attachments: attachments.length > 0 ? [...attachments] : undefined,
      createdAt: Date.now(),
    };

    let sessionKey = active?.key;
    let threadId = active?.threadId ?? "";
    if (sessionKey) {
      // 复用当前会话：历史会话继续，或已点"新会话"但首条消息未发出的本地会话（threadId 为空）
      setActive((prev) => {
        if (!prev || prev.key !== sessionKey) return prev;
        const isFirstQuestion = !prev.messages.some((m) => m.role === "user");
        return {
          ...prev,
          title: isFirstQuestion ? text.slice(0, 20) || prev.title : prev.title,
          messages: [...prev.messages, userMsg],
          updatedAt: Date.now(),
        };
      });
    } else {
      // 尚未进入任何会话：新建本地会话，threadId 留空交由后端生成
      const now = Date.now();
      sessionKey = createId();
      threadId = "";
      const fresh: ChatSession = {
        key: sessionKey,
        threadId: "",
        title: text.slice(0, 20) || "新会话",
        messages: [userMsg],
        createdAt: now,
        updatedAt: now,
      };
      setActive(fresh);
    }

    setInput("");
    setAttachments([]);
    void sendToAssistant(sessionKey as string, threadId, userMsg);
  }, [
    active?.key,
    active?.threadId,
    attachments,
    historyLoading,
    input,
    loading,
    sendToAssistant,
  ]);

  // 当前活动会话若尚未出现在服务端列表（新建未持久化 / 首页未覆盖），置顶展示
  const serverHasActive = active
    ? items.some((i) => i.threadId === active.threadId)
    : false;
  const displayItems =
    active && !serverHasActive
      ? [{ threadId: active.threadId, title: active.title }, ...items]
      : items;

  return (
    <div className={styles.shell}>
      <SessionSidebar
        items={displayItems}
        activeThreadId={active?.threadId ?? null}
        loading={initialLoading}
        loadingMore={loadingMore}
        hasMore={hasMore}
        error={listError}
        deletingThreadId={deletingThreadId}
        onNewSession={handleNewSession}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
        onLoadMore={loadMore}
      />
      <main className={styles.main}>
        <ChatArea
          messages={active?.messages ?? []}
          loading={loading}
          historyLoading={historyLoading}
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
          loading={loading || historyLoading}
          disabled={historyLoading}
        />
      </main>
    </div>
  );
}
