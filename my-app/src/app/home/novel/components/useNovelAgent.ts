"use client";

import { createParser } from "eventsource-parser";
import { useCallback, useRef, useState } from "react";
import type { InspirationItem } from "./types";

/** 图停下来问用户的那一问：话 + 可点的出口 + 交了但还没落库的那一稿 */
export interface NovelAgentQuestion {
  text: string;
  /** 后端给的出口按钮（收下 / 按库里改）。空数组就是普通提问，照旧打字答 */
  options: { id: string; label: string }[];
  /** 那一稿正文。落库之前它只活在后端 checkpoint 里，刷新后靠它重建临时框 */
  draft: { order: number | null; title: string; content: string } | null;
  /**
   * 这一问前面还垫着一句助手的回话（用户没点按钮、而是问了一句，由 chat 答了）。
   *
   * 只在实时路径上有值，要补成一条气泡；水合那一路是空串 —— 那句话已经在 /history 的
   * messages 里了，再补一遍就是两条。
   */
  reply: string;
}

/**
 * 这一轮要落哪一章（后端 resolve 节点定下、writer/editor 还没动笔就发过来）。
 *
 * 前端不再拿"发请求时开着的那一章"当归属 —— 那是覆盖错章的根。kind 为 write_next 时
 * chapterId 是空的，chapters 里也没这一行，按 order 现造一个草稿框；edit 则认 chapterId。
 */
export interface NovelAgentTarget {
  kind: "write_next" | "edit";
  chapterId: string;
  order: number | null;
}

/** 事件名与后端 api/novel/agent.py 的 _sse 一一对应 */
export interface NovelAgentHandlers {
  /** 状态行文案（"正在写这一章…"这类），换掉上一条 */
  onStage?: (text: string) => void;
  /** 这一轮落在哪一章。在第一个 token 之前到，前端据此把在流的稿画对地方 */
  onTarget?: (target: NovelAgentTarget) => void;
  /** 正文从头开始：清空临时框重写。首稿与回炉都会来一次 */
  onProseStart?: () => void;
  /** 正文片段，接在临时框后面 */
  onToken?: (text: string) => void;
  /** 图停下来问用户了（审稿结论 + 收下还是改），要等用户答 */
  onQuestion?: (question: NovelAgentQuestion) => void;
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

/** 上一轮收尾时的样子。status 为 cancelled = 中途断了（客户端断开、超时），前端要提一句 */
export interface NovelRunState {
  status: string;
  intension: string | null;
  at: string | null;
}

/** 后端 GET /pending 的返回：没有待确认的稿时 pending 为 false，lastRun 照给 */
export interface NovelPending extends NovelAgentQuestion {
  pending: boolean;
  /** 这一轮跑到哪儿了；后端没记过就是 null（老书、从没跑过） */
  lastRun: NovelRunState | null;
}

/** 后端给的 lastRun 那一块；缺字段 / 没有都当 null */
function toRun(body: Record<string, unknown>): NovelRunState | null {
  const run = body.lastRun as Record<string, unknown> | null | undefined;
  if (!run || typeof run.status !== "string") return null;
  return {
    status: run.status,
    intension: typeof run.intension === "string" ? run.intension : null,
    at: typeof run.at === "string" ? run.at : null,
  };
}

/** 没稿、也（通常）没上一轮记录时的空返回；pull 不到的后端一律走这里 */
function emptyPending(body?: Record<string, unknown>): NovelPending {
  return {
    pending: false,
    text: "",
    options: [],
    draft: null,
    reply: "",
    lastRun: body ? toRun(body) : null,
  };
}

/** 那一问的载荷；后端在没给按钮 / 没给稿 / 没垫回话时送的是空数组、空对象、空串 */
function toQuestion(data: Record<string, unknown>): NovelAgentQuestion {
  const draft = data.draft as NovelAgentQuestion["draft"] | undefined;
  return {
    text: String(data.text ?? ""),
    options: Array.isArray(data.options)
      ? (data.options as NovelAgentQuestion["options"])
      : [],
    draft: draft?.content ? draft : null,
    reply: String(data.reply ?? ""),
  };
}

/**
 * 问一次后端：这本书还有没有一份交了、没确认落库的稿。
 *
 * 那一稿只活在后端的 checkpoint 里，书架列表里没有它 —— 刷新、换设备、切回这本书时，
 * 正文 / 问题 / 按钮三样全靠这一问重建。拉不到就当没有（不打断用户）。
 */
export async function fetchNovelPending(
  novelId: string,
  chapterId: string,
): Promise<NovelPending> {
  let res: Response;
  try {
    res = await fetch(
      `/api/novel/agent/pending?novelId=${encodeURIComponent(novelId)}` +
        (chapterId ? `&chapterId=${encodeURIComponent(chapterId)}` : ""),
    );
  } catch {
    return emptyPending();
  }
  if (!res.ok) return emptyPending();
  const body = (await res.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body?.pending) return emptyPending(body ?? undefined);
  return { pending: true, ...toQuestion(body), lastRun: toRun(body) };
}

/** 后端 GET /history 的返回：agent 还记得的那段对话（更早的那批已压成 summary） */
export interface NovelHistory {
  /** 用户与助手说过的话，按时间先后 */
  messages: { role: "user" | "assistant"; content: string }[];
  /** 早先几轮压成的一段话；一条都没有时为空串 */
  summary: string;
}

/**
 * 问一次后端：这本书还记着哪些对话。
 *
 * 对话只活在 agent 的 checkpoint 里，前端手上那份是内存里的 —— 刷新、换设备、切回这本书时
 * 全没了，只能靠这一问重建。拉不到就当没有（不打断用户），对话栏空着，别的功能照常。
 */
export async function fetchNovelHistory(novelId: string): Promise<NovelHistory> {
  const empty: NovelHistory = { messages: [], summary: "" };
  let res: Response;
  try {
    res = await fetch(`/api/novel/agent/history?novelId=${encodeURIComponent(novelId)}`);
  } catch {
    return empty;
  }
  if (!res.ok) return empty;
  const body = (await res.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body) return empty;
  const rows = Array.isArray(body.messages) ? body.messages : [];
  return {
    messages: rows.flatMap((row) => {
      const item = row as { role?: unknown; content?: unknown };
      const role = item.role === "user" ? "user" : item.role === "assistant" ? "assistant" : null;
      const content = typeof item.content === "string" ? item.content : "";
      return role && content ? [{ role, content }] : [];
    }),
    summary: typeof body.summary === "string" ? body.summary : "",
  };
}

/**
 * 清空这本书的对话记录（用户在对话框旁点的"清空"）。
 *
 * 对话存在后端的 checkpoint 里，所以这事得后端做 —— 只清前端那些气泡，刷新一下就又回来了。
 * 后端拦着两类情况会把话摆明（"有一稿还没确认落库…"这类），所以失败时抛出去让调用方显示，
 * 不当成"清干净了"。成功才算数，调用方再清本地那份。
 */
export async function clearNovelHistory(novelId: string): Promise<void> {
  const form = new FormData();
  form.append("novelId", novelId);
  const res = await fetch("/api/novel/agent/clear", { method: "POST", body: form });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { error?: string } | null;
    throw new Error(body?.error ?? `清空失败（${res.status}）`);
  }
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
      files?: File[],
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
        // 用户挂上来的附件：同名多次追加，与 fields 里那份元信息同序对应
        for (const file of files ?? []) form.append("files", file);

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
              case "target":
                // TEMP 诊断：确认浏览器跑的是不是这份代码。查完删。
                console.log("[novel-agent] 收到 target 事件", data);
                handlers.onTarget?.({
                  kind: data.kind === "edit" ? "edit" : "write_next",
                  chapterId: typeof data.chapterId === "string" ? data.chapterId : "",
                  order: typeof data.order === "number" ? data.order : null,
                });
                break;
              case "prose_start":
                handlers.onProseStart?.();
                break;
              case "token":
                handlers.onToken?.(String(data.text ?? ""));
                break;
              case "question":
                handlers.onQuestion?.(toQuestion(data));
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

  /**
   * 开一轮：一句话交给图（写新章 / 改这一章 / 闲聊；开书则是那句话开场白）。
   *
   * attachments 是用户挂上来的素材：文件本体走 files 上传，另一份只有字符串字段的元信息进
   * inspirations（顺序一一对应）—— 后端据它把内容和名字配回去，并整份落 novel_inspiration。
   * 没有附件就一个字段都不带，后端按空素材处理。
   */
  const run = useCallback(
    (
      novelId: string,
      text: string,
      chapterId: string,
      handlers: NovelAgentHandlers,
      attachments?: InspirationItem[],
    ) => {
      const files = (attachments ?? []).flatMap((a) => (a.file ? [a.file] : []));
      const inspirations = attachments?.length
        ? JSON.stringify(
            attachments.map((a) => ({
              kind: a.kind,
              name: a.name,
              url: a.url ?? "",
              hasFile: Boolean(a.file),
            })),
          )
        : "";
      return send("run", { novelId, text, chapterId, inspirations }, handlers, files);
    },
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

  /**
   * 掐断这一轮。只是断掉客户端这条流，后端据此把这一轮记成 cancelled，
   * 再进这本书时会提示"上一轮中断了"，不需要另调接口。
   */
  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { run, resume, stop, busy };
}
