"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ChapterList from "../ChapterList";
import LedgerModal from "../LedgerModal";
import NewNovelModal from "../NewNovelModal";
import NovelSidebar from "../NovelSidebar";
import { fetchNovelJSON, invalidateNovel, mutateNovel } from "../useNovelQuery";
import type { NovelAgentHandlers, NovelAgentTarget, NovelHistory } from "../useNovelAgent";
import {
  clearNovelHistory,
  fetchNovelHistory,
  fetchNovelPending,
  useNovelAgent,
} from "../useNovelAgent";
import WorkArea from "../WorkArea";
import {
  toChapterStatus,
  type Chapter,
  type ChapterStatus,
  type InspirationItem,
  type Message,
  type Novel,
  type NovelMetaField,
  type RunChapter,
  type WorkTab,
} from "../types";
import styles from "./index.module.scss";

let seq = 0;
function createId(prefix: string) {
  seq += 1;
  return `${prefix}-${Date.now().toString(36)}-${seq}`;
}

/**
 * 库里一章都没有的书（刚建好的），前端补一个占位章，好让用户在正文区跟 AI 说"写第一章"。
 *
 * id 由书 id 派生，所以重拉书架前后是同一个：占位章被重拉的列表顶掉时，正文区不会莫名换到别的章。
 * 库里真有了第一章之后占位就被顶掉，那一轮的 onFinal 本来就会切到真章节的 id 上。
 */
function pendingChapterId(novelId: string) {
  return `pending:${novelId}`;
}

function pendingChapter(novelId: string): Chapter {
  return {
    id: pendingChapterId(novelId),
    title: "第1章",
    order: 1,
    status: "draft",
    content: "",
    // 它也是"库里还没有这一行"，所以同临时章：状态改不了，章列表里挂个"临时"
    temp: true,
  };
}

/**
 * 待确认的那一稿在书架里是没有的（它只活在后端 checkpoint 里），得在前端给它找个落脚点。
 *
 * id 由书号与章序号派生，所以同一稿反复恢复（切书回来、重进这一章）落到的是同一章，
 * 不会并排造出两个临时章。
 */
function draftChapterId(novelId: string, order: number | null) {
  return `draft:${novelId}:${order ?? 0}`;
}

/**
 * 后端那份历史转成对话栏的气泡。
 *
 * 更早那批已经被 agent 压成一段摘要、原文从 messages 里删了（见 agents/novel/utils/history.py），
 * 摘要单摆一条"前情"顶在最前面 —— 不摆的话，用户看到的历史像是从半截开始，还以为前面丢了。
 */
function toHistoryMessages(history: NovelHistory): Message[] {
  const rows: Message[] = history.messages.map((m) => ({
    id: createId("msg"),
    role: m.role,
    content: m.content,
    createdAt: Date.now(),
  }));
  const summary = history.summary.trim();
  if (summary) {
    rows.unshift({
      id: createId("msg"),
      role: "assistant",
      content: `【前情摘要】\n${summary}`,
      createdAt: Date.now(),
    });
  }
  return rows;
}

/**
 * 一章的序号。认 `order` 字段 —— 库里读来的、前端新建的都带着它，是精确的。
 *
 * 老数据（这一版之前建的临时章）没有 order，才退回从标题里抠"第N章"；再认不出就当没有。
 */
function chapterOrderOf(chapter: Chapter | null): number | null {
  if (!chapter) return null;
  if (typeof chapter.order === "number") return chapter.order;
  const matched = chapter.title.match(/第\s*(\d+)\s*章/);
  return matched ? Number(matched[1]) : null;
}

/** 后端 /novels 的返回体：章节列表里不带正文，正文按章单取 */
interface NovelListResponse {
  total: number;
  novels: {
    id: string;
    title: string;
    wordCount: number;
    tropes: string;
    style: string;
    chapters: {
      id: string;
      title: string;
      order: number;
      status: string;
      wordCount: number;
      /** 保存正文要带回去的版本令牌，原样字符串，见 types.ts 的 Chapter.version */
      version: string;
    }[];
  }[];
}

interface ChapterContentResponse {
  title: string;
  status: string;
  content: string;
  wordCount: number;
  version: string;
}

function toChapter(row: NovelListResponse["novels"][number]["chapters"][number]): Chapter {
  return {
    id: row.id,
    // 标题由模型在正文里写（"# 第1章 标题"），库里空着就按序号补一个，编号口径全书统一用阿拉伯数字
    title: row.title || `第${row.order}章`,
    order: row.order,
    status: toChapterStatus(row.status),
    content: "",
    wordCount: row.wordCount,
    version: row.version,
  };
}

/**
 * 正在跑的那一轮生成：流式正文、状态行、有没有停下等答复。
 *
 * 一本书同时只跑一轮（后端一本只有一个 thread_id，useNovelAgent 里也有单飞守卫），所以只留
 * 一份；但它必须记着自己属于哪一本书、哪一章 —— 稿子只在那一章上渲染，进度行按书挂
 * （对话栏是整本书一条），所以两样都得记着，见下面 runHere 那一段。
 */
interface ActiveRun {
  /** 这一轮挂在哪本书上：对话栏是整本书一条，进度行只认书、不认章 */
  novelId: string;
  /** 发起这一轮时开着的那一章。只用来兜底（target 还没到）；归属认 targetChapterId */
  chapterId: string;
  /** 后端 resolve 定的这一轮要落哪一章；还没到就是 null */
  target: NovelAgentTarget | null;
  /**
   * 这一轮真正落在哪一章的 id —— onTarget / onQuestion 拿 ensure_draft_chapter 定下之后就钉在这儿。
   *
   * write_next 时库里可能还没有这一章，用的一律是 ensure_draft_chapter 现造/命中的那个 id
   * （命中了用户手动建的那一章就用它自己，认不出才现造一个）。**渲染认它** —— 别再拿
   * `draft:${novelId}:${order}` 去重算，那样算出来的是"假设一定要现造"，跟实际落点分叉时
   * 稿子就会画到别人身上（覆盖当前章的那个 bug 就在这儿）。
   */
  targetChapterId: string | null;
  draft: { content: string; streaming: boolean } | null;
  stage: string;
  pendingQuestion: boolean;
  /** 停在确认上时后端给的出口按钮（收下 / 按库里改）；一开跑就清空 */
  options: { id: string; label: string }[];
}

export default function NovelWorkspace() {
  const [novels, setNovels] = useState<Novel[]>([]);
  const [activeNovelId, setActiveNovelId] = useState<string | null>(null);
  const [activeChapterId, setActiveChapterId] = useState<string | null>(null);
  const [tab, setTab] = useState<WorkTab>("text");
  const [collapsed, setCollapsed] = useState(false);
  /** 章节栏自己也折：折起来只留"第N章"，跟小说栏各折各的 */
  const [chapterCollapsed, setChapterCollapsed] = useState(false);
  const [loadError, setLoadError] = useState("");
  /** 正在看台账的那一章，null 表示台账没打开 */
  const [ledgerChapter, setLedgerChapter] = useState<Chapter | null>(null);
  /** 新建小说弹窗开着（设定一问一答全在窗里走完，关掉就是放弃） */
  const [newNovelOpen, setNewNovelOpen] = useState(false);
  /** 对话按小说存，切章不变 —— 后端一本书就是一个 thread，记忆本来就是跨章连着的 */
  const [chats, setChats] = useState<Record<string, Message[]>>({});
  /** 落库后催正文重取一次：改既有章时章 id 没变，下面那个 effect 不会自己重跑 */
  const [contentStamp, setContentStamp] = useState(0);
  /** 这一章在别处被改过、本地这一笔没能保存；等用户自己决定什么时候换最新版 */
  const [conflict, setConflict] = useState<{ novelId: string; chapterId: string } | null>(null);
  /** 正在跑的那一轮（流式正文 / 状态行 / 是否在等答复），null 表示这会儿没有在生成的 */
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);
  /** 已经向哪本书问过一次"历史 + 有没有待确认的稿"，免得每次重渲染都去打后端 */
  const hydrateRef = useRef<string | null>(null);
  /** 已经为哪本书提过一次"上一轮中断了"，免得在几本书之间切来切去时反复说；重开一轮就销账 */
  const toldInterruptedRef = useRef<Set<string>>(new Set());
  /** 手改正文的防抖定时器：按键期间不发，停手 800ms 才落一次库 */
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** 攒着还没发出去的正文（键是 `novelId+chapterId`，切章不影响它认哪一章） */
  const pendingSaveRef = useRef<{
    novelId: string;
    chapterId: string;
    content: string;
    /** 这一笔是拿哪一版改出来的，落库时当版本令牌发回去 */
    version: string;
  } | null>(null);
  const { run, resume, stop, busy } = useNovelAgent();

  const activeNovel = useMemo(
    () => novels.find((n) => n.id === activeNovelId) ?? null,
    [novels, activeNovelId],
  );
  const activeChapter = useMemo(
    () => activeNovel?.chapters.find((c) => c.id === activeChapterId) ?? null,
    [activeNovel, activeChapterId],
  );

  /** 本轮是当前这本书在跑的吗 —— 切书之后别人的进度不该跟过来 */
  const runHere = activeRun && activeRun.novelId === activeNovelId ? activeRun : null;

  /**
   * 这一轮真正落在哪一章上 —— 前端不再拿"发请求时开着的那一章"去猜（那是覆盖错章的根）。
   *
   * 只认 onTarget / onQuestion 钉下的 targetChapterId：那是 ensure_draft_chapter 实际认下的那一章
   * （新章还没落库时就是那个临时框的 id）。target 还没到的那一瞬用发起时那一章兜底。
   */
  const runTargetId = runHere ? runHere.targetChapterId ?? runHere.chapterId : null;
  /** 本轮那章：已经不在书里了（占位章被重拉的列表顶掉之类）就当没有 */
  const runChapter = runTargetId
    ? activeNovel?.chapters.find((c) => c.id === runTargetId) ?? null
    : null;
  /** 挂到导航条上的那一轮 */
  const runBadge: RunChapter | null =
    runHere && runChapter
      ? { id: runChapter.id, title: runChapter.title, pending: runHere.pendingQuestion }
      : null;
  // 稿子 / 待答复只在"当前看的正好是那一章"时交给它渲染；翻去别的章时，
  // 那一章照常显示自己的正文，本轮的东西都留在导航条那一格上。
  const draft = runHere && runTargetId === activeChapterId ? runHere.draft : null;
  // 进度行不按章过滤：对话栏是整本书一条（切章不换会话），agent 在不在想跟用户翻到哪一章无关。
  // 照着章过滤的话，新建 / 切换章节会让"思考中"凭空消失，用户以为 agent 没了。
  const stage = runHere?.stage ?? "";
  const pendingQuestion =
    runHere && runTargetId === activeChapterId ? runHere.pendingQuestion : false;
  /** 出口按钮跟着那一问走：停在确认上才给，重新开跑就没了 */
  const answerOptions = runHere && runTargetId === activeChapterId ? runHere.options : [];
  /** 章节栏要标"待确认"的那一章：本轮停在了它上面（可能就是库里还没这一行的稿） */
  const awaitingChapterId = runHere?.pendingQuestion ? runTargetId : null;

  /**
   * 不给再建新章：这本书已经有一个"新建了还没落库"的章，或者这一稿正等着用户确认。
   *
   * 空书自动补的那个占位章也算 —— 它在列表里本来就挂着"临时"、正文区标题也是"临时"，
   * 用户看着就是个还没落库的章；再点 + 只会把它顶掉、另起一个一样临时的一章，所以按钮该灰着。
   *
   * 放行的那一刻是这一章真的变成库里的行 —— agent 写完、用户在对话里确认，onFinal 重拉书架，
   * 临时章被真章节顶掉，这里自然就 false 了。改既有章那一稿就落在库里已有的那一章上（不是临时
   * 章），所以另按"正等确认"再挡一道：没答它就开新章，正文一跑，上一稿就白写了。
   */
  const createBlocked = useMemo(
    () => !!activeNovel?.chapters.some((c) => c.temp) || awaitingChapterId !== null,
    [activeNovel, awaitingChapterId],
  );

  /** 一本书同时只跑一轮，跑着的时候整条会话封掉；对话是跨章连着的，翻去别的章照旧可读 */
  const chatDisabled = busy;

  /** 把一份 /novels 响应写进 state；keep 给了就落到它指定的书 / 章，否则维持当前选择 */
  const applyNovels = useCallback(
    (
      res: NovelListResponse,
      keep?: { novelId?: string | null; chapterId?: string | null },
    ) => {
      const list: Novel[] = res.novels.map((item) => ({
        id: item.id,
        title: item.title || "未命名小说",
        wordCount: item.wordCount ?? 0,
        tropes: item.tropes ?? "",
        style: item.style ?? "",
        // 设定收齐就算建成，但可能一章都还没写；补个占位章，正文区才有个落脚的地方
        chapters:
          item.chapters.length > 0 ? item.chapters.map(toChapter) : [pendingChapter(item.id)],
      }));
      setNovels(list);
      setActiveNovelId((prev) => keep?.novelId ?? prev ?? list[0]?.id ?? null);
      setActiveChapterId(
        (prev) => keep?.chapterId ?? prev ?? list[0]?.chapters[0]?.id ?? null,
      );
      setLoadError("");
    },
    [],
  );

  /** 重拉书架：一章落库之后要重拉，新章才出现在列表里 */
  const loadNovels = useCallback(
    async (keep?: { novelId?: string | null; chapterId?: string | null }) =>
      applyNovels(
        await fetchNovelJSON<NovelListResponse>("/api/novel/method/novels"),
        keep,
      ),
    [applyNovels],
  );

  /**
   * 把攒着的那一笔正文落库（防抖到点、切章、卸载时都走它）。
   *
   * 回来的只有字数与新的版本令牌：两处字数直接就地写上、令牌换到这一章头上，**不重拉书架** ——
   * 书架里每章的正文都是空的（正文按章单取），重拉会把用户正看着的这一章清空，而正文那个
   * effect 的依赖没变（书 / 章 / 戳都没变），不会自己再取一次。
   */
  const flush_content_save = useCallback(() => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    const pending = pendingSaveRef.current;
    if (!pending) return;
    pendingSaveRef.current = null;

    const form = new FormData();
    form.append("novelId", pending.novelId);
    form.append("chapterId", pending.chapterId);
    form.append("content", pending.content);
    form.append("version", pending.version);
    mutateNovel<{ wordCount: number; novelWordCount: number; updatedAt: string }>(
      "/api/novel/method/chapter/content",
      { method: "POST", body: form },
    )
      .then((res) => {
        setNovels((prev) =>
          prev.map((n) =>
            n.id !== pending.novelId
              ? n
              : {
                  ...n,
                  wordCount: res.novelWordCount,
                  chapters: n.chapters.map((c) =>
                    c.id === pending.chapterId
                      ? { ...c, wordCount: res.wordCount, version: res.updatedAt }
                      : c,
                  ),
                },
          ),
        );
        // 这一笔落库顺带换了令牌：同一章还攒着下一笔的话，把它手上那份也换成新的，否则下一发假冲突
        const next = pendingSaveRef.current;
        if (next && next.novelId === pending.novelId && next.chapterId === pending.chapterId) {
          pendingSaveRef.current = { ...next, version: res.updatedAt };
        }
      })
      .catch((err: unknown) => {
        // 版本对不上（412）：这一章在别处被改过。用户打的字留着，摆条冲突条等他自己决定 ——
        // 自动重取会把他正打的内容冲掉，偷偷重试会静默覆盖别人。
        if (err instanceof Error && (err as { status?: number }).status === 412) {
          setConflict({ novelId: pending.novelId, chapterId: pending.chapterId });
          return;
        }
        // "AI 正在写这一章"（409）等其余失败：原话摆到横幅上让用户自己拿主意
        setLoadError(err instanceof Error ? err.message : "正文没能保存");
      });
  }, []);

  // 书架来自库里：进页面拉一次 /novels，侧栏与章节列表都照它渲染，
  // 各标签页要的 threadId 也是这里的 novels[].id。
  useEffect(() => {
    let alive = true;
    fetchNovelJSON<NovelListResponse>("/api/novel/method/novels")
      .then((res) => {
        if (alive) applyNovels(res);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setLoadError(err instanceof Error ? err.message : "书架加载失败");
      });
    return () => {
      alive = false;
    };
  }, [applyNovels]);

  // 正文按章单取（列表里不带正文）。刚在本地新建、还没落库的章取不到，保持空着就是了。
  useEffect(() => {
    if (!activeNovelId || !activeChapterId) return;
    let alive = true;
    const url =
      `/api/novel/method/chapter/content?threadId=${encodeURIComponent(activeNovelId)}` +
      `&chapterId=${encodeURIComponent(activeChapterId)}`;
    fetchNovelJSON<ChapterContentResponse>(url)
      .then((res) => {
        if (!alive) return;
        setNovels((prev) =>
          prev.map((n) =>
            n.id !== activeNovelId
              ? n
              : {
                  ...n,
                  chapters: n.chapters.map((c) =>
                    c.id === activeChapterId
                      ? {
                          ...c,
                          title: res.title || c.title,
                          status: toChapterStatus(res.status),
                          content: res.content,
                          wordCount: res.wordCount,
                          version: res.version,
                        }
                      : c,
                  ),
                },
          ),
        );
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [activeNovelId, activeChapterId, contentStamp]);

  // 切书 / 切章 / 离开这一页时，把还在防抖窗口里、没发出去的那一笔正文先落库 ——
  // 用户改完立刻翻走，改动不能跟着走掉。pendingSaveRef 自己记着是书 / 章，不靠当前的选中项。
  useEffect(
    () => () => flush_content_save(),
    [activeNovelId, activeChapterId, flush_content_save],
  );

  // 选中的章也可能已经不在书里了（本地新建 / 删除的章从没落库，重拉一次就没了）：别死守着一个
  // 找不到的章让右侧空着，退回这一本的第一章。
  useEffect(() => {
    if (!activeNovel) return;
    if (activeNovel.chapters.some((c) => c.id === activeChapterId)) return;
    setActiveChapterId(activeNovel.chapters[0]?.id ?? null);
  }, [activeNovel, activeChapterId]);

  /** 丢掉某一本（或几本）的对话，键就是 novelId；删章不删对话，整本删掉才清 */
  const dropChats = useCallback((novelIds: string[]) => {
    setChats((prev) => {
      const next = { ...prev };
      for (const id of novelIds) delete next[id];
      return next;
    });
  }, []);

  /**
   * 清空这一本的对话记录（对话框旁边那个按钮）。
   *
   * 后端那份才是真的（前端这些气泡一刷新就没了），所以先让后端清干净、成功了才清本地的 ——
   * 反过来的话，后端没清掉、界面却空了，刷新一下旧对话又冒出来，用户会以为见了鬼。
   * 有一稿还没确认时后端会拒（409）：把它那句话摆到顶部横幅上，那一稿等着人答，先别清。
   */
  const handleClearChat = useCallback(() => {
    if (!activeNovelId || busy) return;
    if (
      !window.confirm(
        "确定清空这一本的对话记录吗？清空后 AI 也不记得之前聊过什么，且不可恢复。",
      )
    )
      return;
    const novelId = activeNovelId;
    clearNovelHistory(novelId)
      .then(() => dropChats([novelId]))
      .catch((err: unknown) => {
        setLoadError(err instanceof Error ? err.message : "清空对话失败");
      });
  }, [activeNovelId, busy, dropChats]);

  const handleSelectNovel = useCallback(
    (id: string) => {
      const novel = novels.find((n) => n.id === id);
      if (!novel) return;
      setActiveNovelId(id);
      setActiveChapterId(novel.chapters[0]?.id ?? null);
    },
    [novels],
  );

  // 点「新建小说」只是把弹窗打开：书是弹窗里跟 agent 一问一答收完设定之后才落库的，
  // 这里不再往内存里塞一本假书（那样刷新就没了，而且也没有设定可写）。
  const handleCreateNovel = useCallback(() => setNewNovelOpen(true), []);

  /** 弹窗收完设定、书已落库：重拉书架并选中它。此时这本书还没有章节，会补上占位章。 */
  const handleNovelCreated = useCallback(
    (novelId: string) => {
      setNewNovelOpen(false);
      loadNovels({
        novelId,
        chapterId: pendingChapterId(novelId),
      }).catch((err: unknown) => {
        setLoadError(err instanceof Error ? err.message : "书架加载失败");
      });
    },
    [loadNovels],
  );

  /**
   * 改小说的元信息：书名（侧栏改的）与类型 / 文风（章节栏头顶那一行就地改的）。
   *
   * 先改本地再发请求：改完立刻见效，不用等一个来回；发失败就退回原来那一句并把后端原话摆到
   * 横幅上 —— 界面上写着新文风、库里还是旧文风（下一章照旧的写）比报个错更糟。不重拉书架：
   * 书架里每章的正文都是空的，重拉会把用户正看着的这一章清空（同 flush_content_save 那段）。
   */
  const handle_edit_novel_meta = useCallback(
    (novel: Novel, field: "title" | NovelMetaField, value: string) => {
      const next = value.trim();
      if (!next || novel[field] === next) return;
      const before = novel[field];
      const patch = (v: string) =>
        setNovels((prev) =>
          prev.map((n) =>
            n.id !== novel.id
              ? n
              : field === "title"
                ? { ...n, title: v }
                : field === "tropes"
                  ? { ...n, tropes: v }
                  : { ...n, style: v },
          ),
        );

      patch(next);
      const form = new FormData();
      form.append("novelId", novel.id);
      form.append(field, next);
      mutateNovel("/api/novel/method/novel", { method: "PATCH", body: form }).catch(
        (err: unknown) => {
          patch(before);
          setLoadError(err instanceof Error ? err.message : "小说信息没能改掉");
        },
      );
    },
    [],
  );

  /** 侧栏改书名走这一条（正文栏头顶那一行改的是类型 / 文风） */
  const handleRenameNovel = useCallback(
    (id: string, title: string) => {
      const novel = novels.find((n) => n.id === id);
      if (novel) handle_edit_novel_meta(novel, "title", title);
    },
    [novels, handle_edit_novel_meta],
  );

  const handleDeleteNovel = useCallback(
    (novel: Novel) => {
      if (!window.confirm(`确定删除小说「${novel.title}」吗？其下所有章节都会一并删除。`))
        return;
      // 删的若是当前这本，先把选择清掉：applyNovels 见到空值就会落到剩下来的第一本，
      // 否则它会守着这个已经不存在的 id，右侧一直空着。
      if (novel.id === activeNovelId) {
        setActiveNovelId(null);
        setActiveChapterId(null);
      }
      mutateNovel(`/api/novel/method/novel?novelId=${encodeURIComponent(novel.id)}`, {
        method: "DELETE",
      })
        .then(() => {
          dropChats([novel.id]);
          return loadNovels();
        })
        .catch((err: unknown) => {
          setLoadError(err instanceof Error ? err.message : "删除失败");
        });
    },
    [activeNovelId, dropChats, loadNovels],
  );

  /**
   * 新建一章：只在前端立一个临时章，库里这时候还没有它。
   *
   * 之后 user 让 agent 写这一章、确认落库，onFinal 重拉书架时它才变成真章节（草稿）。
   * 一本书同时只留一个临时章，所以有这个挡着的时候 + 是灰的。
   */
  const handleCreateChapter = useCallback(() => {
    // createBlocked 挡着的时候按钮根本点不动；这儿再挡一道，免得别处误调
    if (!activeNovel || createBlocked) return;
    // 序号按"当前最大 order + 1"递补，与后端 next_chapter_order 同一口径。不能用
    // chapters.length + 1 —— 章号有跳号（删过章）时两者对不上，这一章就会跟后端要写的
    // 那一章认不到一块儿去，同一个"最新章"在列表里长出两个。
    const order = activeNovel.chapters.reduce((max, c) => Math.max(max, chapterOrderOf(c) ?? 0), 0) + 1;
    const chapter: Chapter = {
      id: createId("chapter"),
      title: `第${order}章`,
      order,
      status: "draft",
      content: "",
      temp: true,
    };
    setNovels((prev) =>
      prev.map((n) =>
        n.id === activeNovel.id ? { ...n, chapters: [...n.chapters, chapter] } : n,
      ),
    );
    setActiveChapterId(chapter.id);
  }, [activeNovel, createBlocked]);

  /**
   * 改章名。先改本地立刻见效，再落库；失败退回原来的名字并把后端原话摆到横幅上。
   *
   * 临时章（库里还没这一行）只改本地 —— 发过去只会 404，用户看得见的改名也不用等到落库。
   */
  const handleRenameChapter = useCallback(
    (chapter: Chapter, title: string) => {
      if (!activeNovelId) return;
      const next = title.trim();
      if (!next || next === chapter.title) return;
      const before = chapter.title;
      const patch = (fields: Partial<Chapter>) =>
        setNovels((prev) =>
          prev.map((n) =>
            n.id !== activeNovelId
              ? n
              : {
                  ...n,
                  chapters: n.chapters.map((c) =>
                    c.id === chapter.id ? { ...c, ...fields } : c,
                  ),
                },
          ),
        );

      patch({ title: next });
      if (chapter.temp) return;

      const form = new FormData();
      form.append("novelId", activeNovelId);
      form.append("chapterId", chapter.id);
      form.append("title", next);
      // 这一笔顺带 bump 了 updatedAt：把新的版本令牌存回去，否则用户接着手改正文会假冲突
      mutateNovel<{ updatedAt: string }>("/api/novel/method/chapter", {
        method: "PATCH",
        body: form,
      })
        .then((res) => patch({ version: res.updatedAt }))
        .catch((err: unknown) => {
          patch({ title: before });
          setLoadError(err instanceof Error ? err.message : "章名没能改掉");
        });
    },
    [activeNovelId],
  );

  /**
   * 改一章的状态（完成 / 草稿 / 待修复），这本是库里的一笔小写。
   *
   * 先改本地再发请求：点完下拉立刻见效，不用等一个来回；发失败（后端不认、断网）就退回原来
   * 那一档并把原话摆到顶部横幅上 —— 界面上的状态跟库里不一致，比报个错更糟。
   */
  const handleChapterStatusChange = useCallback(
    (chapter: Chapter, status: ChapterStatus) => {
      if (!activeNovelId || chapter.temp || chapter.status === status) return;
      const before = chapter.status;
      const patch = (fields: Partial<Chapter>) =>
        setNovels((prev) =>
          prev.map((n) =>
            n.id !== activeNovelId
              ? n
              : {
                  ...n,
                  chapters: n.chapters.map((c) =>
                    c.id === chapter.id ? { ...c, ...fields } : c,
                  ),
                },
          ),
        );

      patch({ status });
      const form = new FormData();
      form.append("novelId", activeNovelId);
      form.append("chapterId", chapter.id);
      form.append("status", status);
      // 同改章名：这一笔也 bump updatedAt，新令牌得存回去，否则下一次手改正文假冲突
      mutateNovel<{ updatedAt: string }>("/api/novel/method/chapter/status", {
        method: "POST",
        body: form,
      })
        .then((res) => patch({ version: res.updatedAt }))
        .catch((err: unknown) => {
          patch({ status: before });
          setLoadError(err instanceof Error ? err.message : "状态没能改掉");
        });
    },
    [activeNovelId],
  );

  /**
   * 删一章。本地先撤掉（撤销按钮立刻见效），再落库；失败就把它插回原位（后端没删掉，
   * 界面上不能少一行）并把原话摆到横幅上。临时章库里没有这一行，删本地就是全删。
   *
   * 库里那一行没了，它名下的台账与章节状态靠外键级联一并走；总字数由后端重算后回传。
   */
  const handleDeleteChapter = useCallback(
    (chapter: Chapter) => {
      if (!activeNovel) return;
      if (!window.confirm(`确定删除「${chapter.title}」吗？删除后不可恢复。`)) return;

      const index = activeNovel.chapters.findIndex((c) => c.id === chapter.id);
      const remaining = activeNovel.chapters.filter((c) => c.id !== chapter.id);
      setNovels((prev) =>
        prev.map((n) => (n.id === activeNovel.id ? { ...n, chapters: remaining } : n)),
      );
      // 对话挂在小说名下，删一章不动它 —— 那一章的事还留在会话里，用户自己翻得到。
      if (chapter.id === activeChapterId) {
        // 删掉当前章后优先落到后一章，没有则落到前一章
        const next = remaining[index] ?? remaining[index - 1] ?? null;
        setActiveChapterId(next?.id ?? null);
      }
      if (chapter.temp) return;
      // 还没发出去的那一笔正文就落在这章上：它是待删的了，别等防抖到点又发一遍
      if (pendingSaveRef.current?.chapterId === chapter.id) pendingSaveRef.current = null;
      // 冲突条也一并收掉：这一章都没了，它指着的那份"最新正文"再载入也没处放
      if (conflict?.chapterId === chapter.id) setConflict(null);

      mutateNovel<{ novelWordCount: number }>(
        `/api/novel/method/chapter?novelId=${encodeURIComponent(activeNovel.id)}` +
          `&chapterId=${encodeURIComponent(chapter.id)}`,
        { method: "DELETE" },
      )
        .then((res) =>
          setNovels((prev) =>
            prev.map((n) =>
              n.id === activeNovel.id ? { ...n, wordCount: res.novelWordCount } : n,
            ),
          ),
        )
        .catch((err: unknown) => {
          setLoadError(err instanceof Error ? err.message : "章节没能删掉");
          setNovels((prev) =>
            prev.map((n) => {
              if (n.id !== activeNovel.id) return n;
              if (n.chapters.some((c) => c.id === chapter.id)) return n;
              const next = [...n.chapters];
              next.splice(Math.max(index, 0), 0, chapter);
              return { ...n, chapters: next };
            }),
          );
        });
    },
    [activeChapterId, activeNovel, conflict],
  );

  /**
   * 手改正文：本地立刻改（按键跟手），停手 800ms 后落一次库。
   *
   * 防抖是必须的 —— 每敲一个字发一次会把后端打满。落库那几个字（本章 / 全书字数）由
   * flush_content_save 回填。临时章（库里还没这一行）只改本地，等它落库了才谈得上存。
   *
   * 令牌只在"这一章的第一次按键"时取：之后 AI 落了库、用户还在同一段上接着打，发的仍是
   * 开始打字时那一版，正好被版本闸挡下来 —— 这就是想要的结果，不该被刷新后的令牌蒙混过去。
   */
  const handleContentChange = useCallback(
    (content: string) => {
      if (!activeNovelId || !activeChapterId) return;
      const chapter = activeNovel?.chapters.find((c) => c.id === activeChapterId);
      setNovels((prev) =>
        prev.map((n) =>
          n.id === activeNovelId
            ? {
                ...n,
                chapters: n.chapters.map((c) =>
                  c.id === activeChapterId ? { ...c, content } : c,
                ),
              }
            : n,
        ),
      );
      if (chapter?.temp) return;
      // 这一章正卡在冲突上：本地照改（他打的字不能吞），但不再攒着发 —— 等他点"载入最新正文"
      if (conflict?.novelId === activeNovelId && conflict.chapterId === activeChapterId) return;

      const pending = pendingSaveRef.current;
      const sameChapter =
        pending?.novelId === activeNovelId && pending.chapterId === activeChapterId;
      pendingSaveRef.current = {
        novelId: activeNovelId,
        chapterId: activeChapterId,
        content,
        version: sameChapter ? pending.version : chapter?.version ?? "",
      };
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => flush_content_save(), 800);
    },
    [activeChapterId, activeNovel, activeNovelId, conflict, flush_content_save],
  );

  /** 追加一条对话。键是 novelId —— 会话整本一条，翻去别的章照样看得见 */
  const pushMessage = useCallback(
    (
      threadId: string,
      role: Message["role"],
      content: string,
      attachments?: InspirationItem[],
    ) => {
      setChats((prev) => ({
        ...prev,
        [threadId]: [
          ...(prev[threadId] ?? []),
          { id: createId("msg"), role, content, attachments, createdAt: Date.now() },
        ],
      }));
    },
    [],
  );

  /**
   * 给某一章在前端落个脚，返回它的 id：架上已经有这一章（改既有章、+ 新建的那一章、空书自动
   * 补的占位章、上一轮交了还没落库的那一稿）就用它自己；没有才现造一个临时章 —— 库里还没有
   * 这一行，正文区要画它得有东西接着。
   *
   * onTarget（开流时）与 onQuestion（交稿停下时）共用这一条：两处认定的章必须是同一个，
   * 否则稿子会在两个框之间跳。
   */
  const ensure_draft_chapter = useCallback(
    (novelId: string, order: number | null, chapters: Chapter[], title?: string) => {
      // 先认章号（认 order 字段，精确）；认不出再认标题全等 —— 老数据没带 order，用户改过名的
      // 章标题里也没有"第N章"，只按章号找会把它当成"架上还没有这一章"，凭空长出一个空的临时章。
      const known =
        (order == null ? undefined : chapters.find((c) => chapterOrderOf(c) === order)) ??
        (title ? chapters.find((c) => c.title === title) : undefined);
      if (known) return known.id;

      const id = draftChapterId(novelId, order);
      const chapter: Chapter = {
        id,
        title: title || (order ? `第${order}章` : "未命名"),
        // 序号记上：下一轮 resolve 报出同一个 order 时，靠它认回这一章，不再另造一个
        order: order ?? undefined,
        status: "draft",
        content: "",
        // 库里没有这一行：状态改不了，章列表里挂个"临时"
        temp: true,
      };
      setNovels((prev) =>
        prev.map((n) =>
          n.id !== novelId
            ? n
            : n.chapters.some((c) => c.id === id)
              ? n
              : {
                  ...n,
                  // 空书自动补的那个占位章跟它占的是同一个位置：换掉，别并排放两个临时章
                  chapters: [
                    ...n.chapters.filter((c) => c.id !== pendingChapterId(novelId)),
                    chapter,
                  ],
                },
        ),
      );
      return id;
    },
    [],
  );

  /**
   * 进页面 / 刷新 / 切回这本书时重建现场：对话栏的历史，加上"忘了确认还挂着的那一稿"。
   *
   * 两样都只活在后端（对话在 checkpoint 的 messages 里，那一稿在快照里），前端手上那份是内存
   * 里的，刷新一下就全没了 —— 恢复没有别的来路。两问串着发、串着落：并行的话谁先回来谁先写
   * chats，后回来的会把先落的盖掉。
   *
   * 只在本页没有这一本的现场时问 —— 本页正跑着、或正停着等答复，手上那份就是最新的，拿快照
   * 去盖反而会把刚流出来的正文抹掉。切回来时会再问一次（切走时标记已经换给别人了），但那时
   * 本地已经有这一本的对话，历史不会再铺一遍。
   */
  useEffect(() => {
    if (!activeNovelId || busy) return;
    if (activeRun?.novelId === activeNovelId) return;
    if (hydrateRef.current === activeNovelId) return;
    hydrateRef.current = activeNovelId;

    const novelId = activeNovelId;
    let alive = true;
    (async () => {
      const history = await fetchNovelHistory(novelId);
      if (!alive) return;
      // 历史当底铺一次。本地已经有这一本的对话（本页刚跑过一轮、或上一段恢复补过）就不铺了 ——
      // 本页手上那份总不比后端旧，铺下去只会把刚流出来的那些话挤掉。
      const seeded = toHistoryMessages(history);
      if (seeded.length) {
        setChats((prev) => (prev[novelId]?.length ? prev : { ...prev, [novelId]: seeded }));
      }

      const res = await fetchNovelPending(novelId, activeChapterId ?? "");
      if (!alive) return;
      if (!res.pending || !res.draft) {
        // 上一轮中途断了（断网、点了停止）：后端记着这一笔，说一句让用户重发。
        // 一本书只说一次 —— 在几本书之间切来切去不该反复念叨；重开一轮就把这条销掉。
        if (res.lastRun?.status === "cancelled" && !toldInterruptedRef.current.has(novelId)) {
          toldInterruptedRef.current.add(novelId);
          pushMessage(novelId, "assistant", "上一轮中断了，重来。");
        }
        return;
      }
      const chapterId = ensure_draft_chapter(
        novelId,
        res.draft.order,
        activeNovel?.chapters ?? [],
        res.draft.title,
      );
      if (!chapterId) return;
      setActiveChapterId(chapterId);
      setActiveRun({
        novelId,
        chapterId,
        // 恢复出来的这一轮没有 target（它只在开流时发一次），按这一稿的序号认那一章
        target: null,
        targetChapterId: chapterId,
        draft: { content: res.draft.content, streaming: false },
        stage: "",
        pendingQuestion: true,
        options: res.options,
      });
      if (res.text) pushMessage(novelId, "assistant", res.text);
    })().catch(() => {});   // 问不到就当没有：不该因为恢复不了而把界面卡住
    return () => {
      alive = false;
    };
  }, [
    activeNovel,
    activeNovelId,
    activeChapterId,
    activeRun,
    busy,
    ensure_draft_chapter,
    pushMessage,
  ]);

  const handleSend = useCallback(
    (
      chapterId: string,
      text: string,
      attachments: InspirationItem[],
      /** 发给后端的原话。点了出口按钮时用它 —— 气泡上显示的仍是按钮那句人话 */
      answer?: string,
    ) => {
      if (!activeNovelId || busy) return;
      // 对话挂在这本书名下，chapterId 只决定这一轮写 / 改的是哪一章（请求里照旧带上）。
      const threadId = activeNovelId;
      // 又开了一轮：上一条"上一轮中断了"的提示销账，真再断了还要能提一遍
      toldInterruptedRef.current.delete(threadId);
      pushMessage(
        threadId,
        "user",
        text,
        attachments.length > 0 ? attachments : undefined,
      );

      // 这一轮先立起来，记在发起它的那一章名下：中途翻去别的章，稿子留在这儿（进度行挂在
      // 整本书的对话栏上，见上面 stage 那一段）。接着答上一轮的问题就复用现成的那一轮 ——
      // 稿子留着，用户正对着它做决定。target 等 resolve 那一事件来了再填（见 onTarget）。
      setActiveRun((prev) =>
        prev && prev.chapterId === chapterId
          ? { ...prev, stage: "", pendingQuestion: false, options: [] }
          : {
              novelId: threadId,
              chapterId,
              target: null,
              targetChapterId: null,
              draft: null,
              stage: "",
              pendingQuestion: false,
              options: [],
            },
      );

      const handlers: NovelAgentHandlers = {
        onStage: (text) =>
          setActiveRun((prev) => (prev ? { ...prev, stage: text } : prev)),
        // 后端定下这一轮要落哪一章：给在流的这一稿定归属，不再拿"发请求时开着的那一章"猜。
        // 造章那一步（setNovels）放在 updater 外面 —— updater 里带副作用，StrictMode 下会跑两遍。
        onTarget: (target) => {
          // edit 的 target 直接指名道姓给了 chapterId，那一章本来就在架上，不必按章号去猜
          // （用户改过标题的章按"第N章"认不出来）；write_next 才是要现造落脚点的那一路。
          const landed = target.chapterId
            ? target.chapterId
            : ensure_draft_chapter(threadId, target.order, activeNovel?.chapters ?? []);
          // TEMP 诊断：确认落点认成了哪一章。查完删。
          console.log("[novel] onTarget", { target, landed, 发起时那一章: chapterId });
          // 落点钉下来：架上已有（+ 新建的那一章、上一轮留下的临时框）就用它自己，没有才现造一个。
          // 渲染认的是它 —— 见 runTargetId。
          setActiveRun((prev) =>
            prev ? { ...prev, target, targetChapterId: landed || prev.targetChapterId } : prev,
          );
          // 写新章时视图一定跟到落脚的那一章上：不然在流的正文没地方画（新章本来就该是当前这一章）。
          // 已经在那一章上就不动（用户正看着它等正文）；改既有章也不动他。
          if (target.kind === "write_next" && landed && landed !== chapterId) {
            setActiveChapterId(landed);
          }
        },
        // 回炉重写也会再来一次：临时框清空重来 —— 覆盖，不是追加
        // 正文到头重来不切标签页：用户这会儿可能正在别的章、别的标签页上翻东西，
        // 生成照跑，接不接着看由他自己决定。
        onProseStart: () =>
          setActiveRun((prev) =>
            prev ? { ...prev, draft: { content: "", streaming: true } } : prev,
          ),
        onToken: (chunk) =>
          setActiveRun((prev) =>
            prev
              ? {
                  ...prev,
                  draft: {
                    content: (prev.draft?.content ?? "") + chunk,
                    streaming: true,
                  },
                }
              : prev,
          ),
        onQuestion: (question) => {
          // 这一问是"用户问了一句、由 chat 答完了"之后重摆的：先补上那句答复，再摆问题。
          // 顺序不能反 —— 他看到的该是「我的问题 → 助手的答复 → 重摆的这一问」。
          // 水合那一路 reply 是空串（答复已在 /history 里），这条分支自然跳过。
          if (question.reply) pushMessage(threadId, "assistant", question.reply);
          if (question.text) pushMessage(threadId, "assistant", question.text);
          // 后端交的那一稿比流里拼起来的可信（被 /run 挡回来的那一次一个字都没流），
          // 它挂在哪一章上由 ensure_draft_chapter 定：多半就是 onTarget 已经造好的那个框，
          // 挡回来的那一轮则要另立一个。
          const landed = question.draft
            ? ensure_draft_chapter(
                threadId,
                question.draft.order,
                activeNovel?.chapters ?? [],
                question.draft.title,
              )
            : "";
          setActiveRun((prev) =>
            prev
              ? {
                  ...prev,
                  chapterId: landed || prev.chapterId,
                  // 交稿这一问把落点最终钉死：onTarget 那一次认下的多半就是它，认出别的才换
                  targetChapterId: landed || prev.targetChapterId,
                  draft: question.draft
                    ? { content: question.draft.content, streaming: false }
                    : prev.draft
                      ? { ...prev.draft, streaming: false }
                      : null,
                  options: question.options,
                  stage: "",
                  pendingQuestion: true,
                }
              : prev,
          );
          // 只有"这一稿根本不是他手上那一章"时才把视图搬过去（被 /run 挡回来的那一次就是这样）；
          // 正常写着的这一章，用户翻去别的章看别的，不该被拽回来。
          if (landed && landed !== chapterId) setActiveChapterId(landed);
        },
        onFinal: (data) => {
          if (data.message) pushMessage(threadId, "assistant", data.message);
          setActiveRun(null);
          // 这一轮可能补了人物 / 世界规则 / 大纲（都在 update 节点落库）：面板缓存作废，
          // 此刻开着的那个标签页自己重拉一次。闲聊那一轮也会走到这儿，白作废一次而已。
          if (activeNovelId) invalidateNovel(activeNovelId);

          // 只有写新章那一轮才有"新东西"要接：chapterId 是刚落库那一章的真 id，把书架重拉一遍
          // 让新章进列表、并切过去看它。（对话挂在小说名下，不用跟着章 id 搬。）
          //
          // 其余轮次的 chapterId 不能信：active_chapter 是跨轮留着的，闲聊、没改成的稿这一轮
          // 什么都没落库（图走的是 intension → chat → update → END，load 都没跑），它给出的还
          // 是上一轮写的那一章。照着它切视图，人就被从正看着的章上甩走，本地新建、
          // 还没落库的那一章也会被重拉的书架冲掉。
          if (data.intension === "write" && data.chapterId && data.chapterId !== chapterId) {
            loadNovels({ novelId: activeNovelId, chapterId: data.chapterId })
              .then(() => setContentStamp((v) => v + 1))
              .catch(() => {});
            return;
          }
          // 改既有章时章 id 没变，正文（连同刚定成的 done）光靠 effect 不会刷新，靠这个戳重取一次。
          setContentStamp((v) => v + 1);
        },
        onError: (message) => {
          pushMessage(threadId, "assistant", `[错误] ${message}`);
          setActiveRun(null);
        },
      };

      // 上一轮停下来的那个问题还等着答复：这一句就是答它
      // 附件跟着这一轮一起送（文件本体 + 元信息），后端落 novel_inspiration 并拼进写作用的提示词。
      // 答上一轮那一问时不带：那一轮已经在跑了，素材也早随发起它那次落过库了。
      if (pendingQuestion) resume(activeNovelId, answer ?? text, chapterId, handlers);
      else run(activeNovelId, text, chapterId, handlers, attachments);
    },
    [
      activeNovel,
      activeNovelId,
      busy,
      ensure_draft_chapter,
      loadNovels,
      pendingQuestion,
      pushMessage,
      resume,
      run,
    ],
  );

  /**
   * 点了确认环节的出口按钮（收下 / 按库里改）：照它答，用户不必自己把"收下"打出来。
   *
   * 走的还是 handleSend 那条路 —— 对话里留一句人话，发给后端的却是可认的选项（后端认得出就
   * 不再过模型判）。
   */
  const handleAnswer = useCallback(
    (option: { id: string; label: string }) => {
      if (!activeChapter) return;
      handleSend(activeChapter.id, option.label, [], JSON.stringify({ option: option.id }));
    },
    [activeChapter, handleSend],
  );

  /**
   * 掐断这一轮生成（对话栏上那个"停止"）。
   *
   * 只断客户端这条流，后端据此把这一轮记成 cancelled（下次进这本书会提一句"上一轮中断了"）。
   * 这一轮现造的那个临时框也撤掉 —— 稿子从没落过库，留着就是个空壳。只撤这儿自己造的：
   * 落点若是用户手动建的那一章（临时章，但人在用），停止不该把它一并抹了。
   */
  const handle_stop = useCallback(() => {
    stop();
    if (activeNovelId) {
      pushMessage(activeNovelId, "assistant", "已停止生成。");
      const target = activeRun?.target;
      const landed = activeRun?.targetChapterId;
      if (
        target?.kind === "write_next" &&
        landed &&
        landed === draftChapterId(activeNovelId, target.order)
      ) {
        setNovels((prev) =>
          prev.map((n) =>
            n.id !== activeNovelId
              ? n
              : { ...n, chapters: n.chapters.filter((c) => c.id !== landed) },
          ),
        );
      }
    }
    setActiveRun(null);
  }, [activeNovelId, activeRun, pushMessage, stop]);

  /**
   * 冲突条上那个"载入最新正文"：丢掉自己手上这一份，取库里那一版（连版本令牌一起换新）。
   *
   * 这一步必须由用户按 —— 自动重取会把他正在打的字冲掉，偷偷重试会静默覆盖别人。
   */
  const handle_reload_conflict = useCallback(() => {
    if (!conflict) return;
    setConflict(null);
    // 冲突可能不是当前这一章（他改完又翻去别处了）：先把视图搬回去，再催正文重取
    setActiveChapterId(conflict.chapterId);
    setContentStamp((v) => v + 1);
  }, [conflict]);

  // 会话是整本书一条：切章时右侧不动，只有切书才换一份
  const messages = activeNovelId ? chats[activeNovelId] ?? [] : [];

  return (
    <div className={styles.shell}>
      {loadError && <div className={styles.notice}>{loadError}</div>}
      {conflict?.novelId === activeNovelId ? (
        <div className={styles.conflict}>
          <span>这一章在别处被改过，你这次的改动没有保存。</span>
          <button type="button" className={styles.conflictAction} onClick={handle_reload_conflict}>
            载入最新正文
          </button>
        </div>
      ) : null}
      <NovelSidebar
        novels={novels}
        activeNovelId={activeNovelId}
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((v) => !v)}
        onSelectNovel={handleSelectNovel}
        onCreateNovel={handleCreateNovel}
        onRenameNovel={handleRenameNovel}
        onDeleteNovel={handleDeleteNovel}
      />
      <ChapterList
        novel={activeNovel}
        activeChapterId={activeChapterId}
        collapsed={chapterCollapsed}
        onToggleCollapse={() => setChapterCollapsed((v) => !v)}
        showActions={!collapsed && !chapterCollapsed}
        createBlocked={createBlocked}
        awaitingChapterId={awaitingChapterId}
        onSelectChapter={setActiveChapterId}
        onCreateChapter={handleCreateChapter}
        onRenameChapter={handleRenameChapter}
        onDeleteChapter={handleDeleteChapter}
        onChangeStatus={handleChapterStatusChange}
        onShowLedger={setLedgerChapter}
        onEditMeta={(field, value) => {
          if (activeNovel) handle_edit_novel_meta(activeNovel, field, value);
        }}
      />
      <WorkArea
        tab={tab}
        onTabChange={setTab}
        threadId={activeNovelId}
        chapter={activeChapter}
        onContentChange={handleContentChange}
        onChangeStatus={(status) => {
          if (activeChapter) handleChapterStatusChange(activeChapter, status);
        }}
        messages={messages}
        onSend={(text, attachments) => {
          if (activeChapter) handleSend(activeChapter.id, text, attachments);
        }}
        draft={draft}
        stage={stage}
        chatDisabled={chatDisabled}
        running={busy}
        onStop={handle_stop}
        pendingQuestion={pendingQuestion}
        answerOptions={answerOptions}
        onAnswer={handleAnswer}
        onClear={handleClearChat}
        runChapter={runBadge}
      />
      <LedgerModal
        threadId={activeNovelId}
        chapter={ledgerChapter}
        onClose={() => setLedgerChapter(null)}
      />
      {newNovelOpen && (
        <NewNovelModal
          onClose={() => setNewNovelOpen(false)}
          onCreated={handleNovelCreated}
        />
      )}
    </div>
  );
}
