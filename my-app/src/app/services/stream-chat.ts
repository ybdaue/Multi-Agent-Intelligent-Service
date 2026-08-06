import { createParser } from "eventsource-parser";
import { request } from "@/lib/fetch";

interface StreamChatOptions {
  onToken: (token: string) => void;
  onThreadId?: (id: string) => void;
  onDone?: () => void;
  onError?: (error: string) => void;
  signal?: AbortSignal;
}

export async function streamChat(url: string, body: object, options: StreamChatOptions) {
  const { onToken, onThreadId, onDone, onError, signal } = options;

  const res = await request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
    timeout: 0, // 流式请求不设超时
  });

  if (!res.ok || !res.body) {
    const msg = res.ok ? "no body" : `${res.status} ${res.statusText}`;
    onError?.(`请求失败: ${msg}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();

  const parser = createParser({
    onEvent: (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.token) {
          onToken(data.token);
        }
        if (data.thread_id) {
          onThreadId?.(data.thread_id);
        }
        if (data.done) {
          onDone?.();
        }
        if (data.error) {
          onError?.(data.error);
        }
      } catch (err) {
        onError?.(`解析错误: ${err}`);
      }
    },
  });

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    parser.feed(decoder.decode(value, { stream: true }));
  }
}
