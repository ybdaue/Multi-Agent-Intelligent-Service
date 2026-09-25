"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { request } from "@/lib/fetch";

/** 缓存条目活多久算新鲜。只是兜底 —— 真正的失效靠 invalidateNovel（见下）。 */
const TTL = 60_000;

/** 键是查询 URL（URL 里都带 threadId，所以各本书、各张表的查询天然分得开） */
const cache = new Map<string, { data: unknown; at: number }>();

/** 失效计数器：加一就让在用的面板重新拉一次 */
let epoch = 0;

const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getEpoch() {
  return epoch;
}

function notify() {
  for (const listener of listeners) listener();
}

/**
 * 作废某一本书的全部查询：写完一章、agent 补了人物 / 世界规则 / 大纲之后调。
 *
 * 认 URL 里 threadId 那一段 —— 三个使用方（SettingPanel / ImpactsPanel / LedgerModal）的
 * URL 都是 `…?threadId=${encodeURIComponent(threadId)}` 这个形状，所以一次调用就把这本书的
 * 面板、台账、受影响点一起清掉。此刻开着的那个面板会自己重拉（旧数据一直在界面上，不闪）。
 *
 * 为什么只标过期、不删条目：删了的话，正开着的面板会先退回"加载中…"再出新数据，看着像闪了
 * 一下。标成过期（at = 0）之后旧数据还读得到，effect 里再静默换新的。
 *
 * 写入方只有 agent 一个，而且全部落在父图的 update 节点里（agents/novel/nodes/update.py：
 * 章节 + 新造实体 + 设定改动 + 影响台账），update 跑完就是那一轮的 final，所以调用点只有
 * NovelWorkspace 的 onFinal 一处；TTL 只是万一有漏网写路径时的兜底。
 */
export function invalidateNovel(novelId: string) {
  const needle = `threadId=${encodeURIComponent(novelId)}`;
  for (const [key, entry] of cache) {
    if (key.includes(needle)) cache.set(key, { ...entry, at: 0 });
  }
  epoch += 1;
  notify();
}

/**
 * 拿一次小说侧的只读 JSON。
 *
 * 非 2xx 时优先把代理/后端给的那句话抛出来（"小说不存在"、"后端响应超时"），
 * 比 requestJSON 那句"请求失败 (502)"对用户有用。
 *
 * **不缓存**：缓存只属于下面的 useNovelQuery。本函数还供 NovelWorkspace 拉书架与正文，
 * 那两处是每一轮都要重拉的（新章得出现在列表里），顺手缓存会让它们拿回旧数据。
 *
 * 非 2xx 抛的错上挂着 status：调用方要靠它分辨"版本对不上"（412）与别的失败。
 */
export async function fetchNovelJSON<T>(url: string): Promise<T> {
  const res = await request(url);
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { error?: string } | null;
    throw Object.assign(new Error(body?.error || `请求失败（${res.status}）`), {
      status: res.status,
    });
  }
  return (await res.json()) as T;
}

/**
 * 小说侧的一次写（改书名 / 删书）。
 *
 * 与 fetchNovelJSON 同一套错误口径：非 2xx 优先抛后端那句话（"小说不存在"），而不是
 * "请求失败 (404)"。成没成看抛不抛异常，调用方成功之后自己去重拉书架。
 *
 * 非 2xx 抛的错上挂着 status：调用方要靠它分辨"版本对不上"（412）与别的失败。
 */
export async function mutateNovel<T = unknown>(
  url: string,
  options: RequestInit,
): Promise<T> {
  const res = await request(url, options);
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { error?: string } | null;
    throw Object.assign(new Error(body?.error || `请求失败（${res.status}）`), {
      status: res.status,
    });
  }
  return (await res.json().catch(() => null)) as T;
}

/**
 * 拉一次小说侧的只读接口，带缓存。
 *
 * url 传 null 就什么都不请求（还没选小说、弹窗没打开），一律回空 —— 否则上一次的数据会挂
 * 在那儿，用户会以为看到的是当前这本的。url 变了重拉；命中缓存就直接给（第一帧就是内容，
 * 不经过"加载中…"），过期了在后台静默重拉一次。
 *
 * 数据源就是上面那张表，用 useSyncExternalStore 在渲染期读它：缓存命中时首帧即内容，比
 * "useEffect 里 setState"少闪一下加载文案。拉回来的响应一律先落缓存再通知，所以卸载中的
 * 组件不会拿到已经没用的数据 —— 缓存是全局的，留在库里下次进这个标签页还是它。
 */
export function useNovelQuery<T>(url: string | null) {
  const getEntry = useCallback(() => (url ? cache.get(url) ?? null : null), [url]);
  const entry = useSyncExternalStore(subscribe, getEntry, () => null);
  // 失效后要重新拉：上面那份快照只说明"数据变了"，重拉的时机得靠这个数跟着变
  const version = useSyncExternalStore(subscribe, getEpoch, () => 0);
  /** 拉失败的那一条，记着是哪个 url 的错（换了 url 就不该再提它） */
  const [failure, setFailure] = useState<{ url: string; error: string } | null>(null);

  useEffect(() => {
    if (!url) return;
    const hit = cache.get(url);
    if (hit && Date.now() - hit.at < TTL) return;  // 手上这份还新鲜，不打后端

    let alive = true;
    fetchNovelJSON<T>(url)
      .then((data) => {
        // 落缓存再通知：此刻开着的面板自己会读出新数据，不用这里去 setState
        cache.set(url, { data, at: Date.now() });
        notify();
      })
      .catch((err: unknown) => {
        // 手里有这本书的旧数据就留着：网络抖一下不该把面板清空。真的一无所有才报错。
        if (alive && !cache.get(url)) {
          setFailure({
            url,
            error: err instanceof Error ? err.message : "加载失败",
          });
        }
      });
    return () => {
      alive = false;
    };
  }, [url, version]);

  if (!url) return { data: null, loading: false, error: "" };
  if (!entry) {
    const error = failure?.url === url ? failure.error : "";
    return { data: null, loading: !error, error };
  }
  return { data: entry.data as T, loading: false, error: "" };
}
