"use client";

import { createParser } from "eventsource-parser";
import { useCallback, useRef, useState } from "react";

/** 事件名与后端 api/novel/agent.py 的 _sse 一一对应 */
export interface NovelAgentHandlers {
  /** 状态行文案（"正在写这一章…"这类），换掉上一条 */
  onStage?: (text: string) => void;
  /** 正文从头开始：清空临时框重写。首稿与回炉都会来一次 */
  onProseStart?: () => void;
  /** 正文片段，接在临时框后面 */
  onToken?: (text: string) => void;
  /** 图停下来问用户了（审稿结论 + 收下还是改），要等用户答 */
  onQuestion?: (text: string) => void;
  /** 这一轮跑完了，这一章也落库了 */
  onFinal?: (data: NovelAgentFinal) => void;
  onError?: (message: string) => void;
}

export interface NovelAgentFinal {
  message: string;
  intension?: string;
  chapterId: string;
  chapterTitle: string;
  chapterOrder: number | null;
  chapterWordCount: number;
  /** 开书那条路（api/novel/setup.py）才有：true = 这本书建好了，前端关窗刷新书架 */
  saved?: boolean;
  novelId?: string;
}

/**
 * 驱动小说图的流式问答。
 *
 * 走自家 /api/novel/{base}/run 与 /resume 两个转发口（SSE），不用 services/stream-chat：
 * 那边只认 {token, thread_id, done, error} 的裸格式，跟后端这套事件名对不上。
 *
 * base 选哪个图：写章走 "agent"（NovelWorkspace），开书走 "setup"（NewNovelModal）。
 * 两个图的 SSE 事件协议一致，所以共用这一个 hook，只是转发口不同。
 */
export function useNovelAgent(base: "agent" | "setup" = "agent") {
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (
      action: "run" | "resume",
      fields: Record<string, string>,
      handlers: NovelAgentHandlers,
    ) => {
      // 上一轮还没收尾就别开新的（同一 thread 上并发跑两轮会把图搅乱）
      if (abortRef.current) return;
      const controller = new AbortController();
      abortRef.current = controller;
      setBusy(true);

      try {
        const form = new FormData();
        for (const [key, value] of Object.entries(fields)) {
          if (value) form.append(key, value);
        }

        const res = await fetch(`/api/novel/${base}/${action}`, {
          method: "POST",
          body: form,
          signal: controller.signal,
        });

        if (!res.ok) {
          const body = (await res.json().catch(() => null)) as { error?: string } | null;
          handlers.onError?.(body?.error ?? `请求失败（${res.status}）`);
          return;
        }
        if (!res.body) {
          handlers.onError?.("响应无数据");
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        const parser = createParser({
          onEvent: (event) => {
            let data: Record<string, unknown>;
            try {
              data = JSON.parse(event.data) as Record<string, unknown>;
            } catch {
              return; // 解析不了的事件忽略（session / done 也走这里之外的正常分支）
            }
            switch (event.event) {
              case "stage":
                handlers.onStage?.(String(data.text ?? ""));
                break;
              case "prose_start":
                handlers.onProseStart?.();
                break;
              case "token":
                handlers.onToken?.(String(data.text ?? ""));
                break;
              case "question":
                handlers.onQuestion?.(String(data.text ?? ""));
                break;
              case "final":
                handlers.onFinal?.(data as unknown as NovelAgentFinal);
                break;
              case "error":
                handlers.onError?.(String(data.message ?? "服务异常"));
                break;
              default:
                break; // session / done：前端没有额外动作
            }
          },
        });

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          parser.feed(decoder.decode(value, { stream: true }));
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        handlers.onError?.("无法连接 AI 服务");
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        setBusy(false);
      }
    },
    [base],
  );

  /** 开一轮：一句话交给图（写新章 / 改这一章 / 闲聊；开书则是那句话开场白） */
  const run = useCallback(
    (novelId: string, text: string, chapterId: string, handlers: NovelAgentHandlers) =>
      send("run", { novelId, text, chapterId }, handlers),
    [send],
  );

  /** 答图上一次停下来的问题（收下这一稿 / 说一句往哪儿改） */
  const resume = useCallback(
    (
      novelId: string,
      answer: string,
      chapterId: string,
      handlers: NovelAgentHandlers,
    ) => send("resume", { novelId, answer, chapterId }, handlers),
    [send],
  );

  return { run, resume, busy };
}
