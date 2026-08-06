"use client";

import { useState, useCallback, useRef } from "react";
import FinanceSidebar from "../../components/SideBarRight";
import { streamChat } from "@/app/services/stream-chat";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function ChatWidget() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "您好！我是您的 AI 股票分析师。您可以问我任何关于股票的问题 —— 无论是股价、技术分析、基本面，还是最新资讯。",
    },
  ]);
  const [chatLoading, setChatLoading] = useState(false);
  const [threadId, setThreadId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  function handleNewChat() {
    setMessages([
      {
        role: "assistant",
        content:
          "您好！我是您的 AI 股票分析师。您可以问我任何关于股票的问题 —— 无论是股价、技术分析、基本面，还是最新资讯。",
      },
    ]);
    setThreadId(null);
  }

  const handleSendMessage = useCallback(
    async (userMsg: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
      setChatLoading(true);

      try {
        setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

        let content = "";
        await streamChat(
          "/api/finance/agent",
          { message: userMsg, thread_id: threadId },
          {
            signal: controller.signal,
            onToken: (token) => {
              content += token;
              setMessages((prev) => {
                const copy = [...prev];
                copy[copy.length - 1] = { role: "assistant", content };
                return copy;
              });
            },
            onThreadId: (id) => setThreadId(id),
            onError: (err) => {
              content += `\n\n[错误] ${err}`;
              setMessages((prev) => {
                const copy = [...prev];
                copy[copy.length - 1] = { role: "assistant", content };
                return copy;
              });
            },
          },
        );
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;

        console.error("Agent stream error:", err);
        const errorMsg =
          "抱歉，无法连接到分析引擎。请确保 Python 后端服务正在运行。";
        setMessages((prev) => {
          if (
            prev.length > 0 &&
            prev[prev.length - 1].role === "assistant" &&
            prev[prev.length - 1].content === ""
          ) {
            const copy = [...prev];
            copy[copy.length - 1] = {
              role: "assistant",
              content: errorMsg,
            };
            return copy;
          }
          return [
            ...prev,
            { role: "assistant", content: errorMsg },
          ];
        });
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
        setChatLoading(false);
      }
    },
    [threadId],
  );

  return (
    <FinanceSidebar
      messages={messages}
      onSendMessage={handleSendMessage}
      onNewChat={handleNewChat}
      loading={chatLoading}
    />
  );
}
