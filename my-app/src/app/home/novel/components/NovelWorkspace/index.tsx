"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ChapterList from "../ChapterList";
import LedgerModal from "../LedgerModal";
import NewNovelModal from "../NewNovelModal";
import NovelSidebar from "../NovelSidebar";
import { fetchNovelJSON, invalidateNovel, mutateNovel } from "../useNovelQuery";
import type { NovelAgentHandlers } from "../useNovelAgent";
import { useNovelAgent } from "../useNovelAgent";
import WorkArea from "../WorkArea";
import {
  toChapterStatus,
  type Chapter,
  type ChapterStatus,
  type InspirationItem,
  type Message,
  type Novel,
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
    status: "draft",
    content: "",
    // 它也是"库里还没有这一行"，所以同临时章：状态改不了，章列表里挂个"临时"
    temp: true,
  };
}

/** 占位章是空书自动补的，不占"一次只许建一个"那个名额 —— 点 + 就是拿它当第一章 */
function isPlaceholder(chapter: Chapter, novelId: string) {
  return chapter.id === pendingChapterId(novelId);
}

/** 后端 /novels 的返回体：章节列表里不带正文，正文按章单取 */
interface NovelListResponse {
  total: number;
  novels: {
    id: string;
    title: string;
    chapters: {
      id: string;
      title: string;
      order: number;
      status: string;
      wordCount: number;
    }[];
  }[];
}

interface ChapterContentResponse {
  title: string;
  status: string;
  content: string;
}

function toChapter(row: NovelListResponse["novels"][number]["chapters"][number]): Chapter {
  return {
    id: row.id,
    // 标题由模型在正文里写（"# 第1章 标题"），库里空着就按序号补一个，编号口径全书统一用阿拉伯数字
    title: row.title || `第${row.order}章`,
    status: toChapterStatus(row.status),
    content: "",
  };
}

/**
 * 正在跑的那一轮生成：流式正文、状态行、有没有停下等答复。
 *
 * 一本书同时只跑一轮（后端一本只有一个 thread_id，useNovelAgent 里也有单飞守卫），所以只留
 * 一份；但它必须记着自己属于哪一章 —— 用户中途翻去别的章时，稿子和进度不能跟过去。
 */
interface ActiveRun {
  chapterId: string;
  draft: { content: string; streaming: boolean } | null;
  stage: string;
  pendingQuestion: boolean;
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
  /** 正在跑的那一轮（流式正文 / 状态行 / 是否在等答复），null 表示这会儿没有在生成的 */
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);
  const { run, resume, busy } = useNovelAgent();

  const activeNovel = useMemo(
    () => novels.find((n) => n.id === activeNovelId) ?? null,
    [novels, activeNovelId],
  );
  const activeChapter = useMemo(
    () => activeNovel?.chapters.find((c) => c.id === activeChapterId) ?? null,
    [activeNovel, activeChapterId],
  );

  /**
   * 这本书已经有一个"新建了还没落库"的章：这时候不给再建。
   *
   * 放行的那一刻是这一章真的变成库里的行 —— agent 写完、用户在对话里确认，onFinal 重拉书架，
   * 临时章被真章节顶掉，这里自然就 false 了。占位章不算数：那不是用户建的，见 isPlaceholder。
   */
  const createBlocked = useMemo(
    () =>
      !!activeNovel?.chapters.some(
        (c) => c.temp && !isPlaceholder(c, activeNovel.id),
      ),
    [activeNovel],
  );

  /** 本轮那章：已经不在书里了（占位章被重拉的列表顶掉之类）就当没有 */
  const runChapter = activeRun
    ? activeNovel?.chapters.find((c) => c.id === activeRun.chapterId) ?? null
    : null;
  /** 挂到导航条上的那一轮 */
  const runBadge: RunChapter | null =
    activeRun && runChapter
      ? { id: runChapter.id, title: runChapter.title, pending: activeRun.pendingQuestion }
      : null;
  // 稿子 / 进度 / 待答复只在"当前看的正好是那一章"时交给它渲染；翻去别的章时，
  // 那一章照常显示自己的正文，本轮的东西都留在导航条那一格上。
  const draft = activeRun && activeRun.chapterId === activeChapterId ? activeRun.draft : null;
  const stage = activeRun && activeRun.chapterId === activeChapterId ? activeRun.stage : "";
  const pendingQuestion =
    activeRun && activeRun.chapterId === activeChapterId ? activeRun.pendingQuestion : false;
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

  const handleRenameNovel = useCallback(
    (id: string, title: string) => {
      const next = title.trim();
      if (!next) return;
      const form = new FormData();
      form.append("novelId", id);
      form.append("title", next);
      mutateNovel("/api/novel/method/novel", { method: "POST", body: form })
        .then(() => loadNovels({ novelId: id }))
        .catch((err: unknown) => {
          setLoadError(err instanceof Error ? err.message : "改名失败");
        });
    },
    [loadNovels],
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
    if (!activeNovel || createBlocked) return;
    // 空书那个占位章换成这一章，别在"第1章"底下再挂一个"第2章"
    const kept = activeNovel.chapters.filter((c) => !isPlaceholder(c, activeNovel.id));
    const chapter: Chapter = {
      id: createId("chapter"),
      title: `第${kept.length + 1}章`,
      status: "draft",
      content: "",
      temp: true,
    };
    setNovels((prev) =>
      prev.map((n) =>
        n.id === activeNovel.id ? { ...n, chapters: [...kept, chapter] } : n,
      ),
    );
    setActiveChapterId(chapter.id);
  }, [activeNovel, createBlocked]);

  const handleRenameChapter = useCallback(
    (id: string, title: string) => {
      if (!activeNovelId) return;
      setNovels((prev) =>
        prev.map((n) =>
          n.id === activeNovelId
            ? {
                ...n,
                chapters: n.chapters.map((c) => (c.id === id ? { ...c, title } : c)),
              }
            : n,
        ),
      );
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
      const patch = (next: ChapterStatus) =>
        setNovels((prev) =>
          prev.map((n) =>
            n.id !== activeNovelId
              ? n
              : {
                  ...n,
                  chapters: n.chapters.map((c) =>
                    c.id === chapter.id ? { ...c, status: next } : c,
                  ),
                },
          ),
        );

      patch(status);
      const form = new FormData();
      form.append("novelId", activeNovelId);
      form.append("chapterId", chapter.id);
      form.append("status", status);
      mutateNovel("/api/novel/method/chapter/status", { method: "POST", body: form }).catch(
        (err: unknown) => {
          patch(before);
          setLoadError(err instanceof Error ? err.message : "状态没能改掉");
        },
      );
    },
    [activeNovelId],
  );

  const handleDeleteChapter = useCallback(
    (chapter: Chapter) => {
      if (!activeNovel) return;
      if (!window.confirm(`确定删除「${chapter.title}」吗？删除后不可恢复。`)) return;

      const remaining = activeNovel.chapters.filter((c) => c.id !== chapter.id);
      setNovels((prev) =>
        prev.map((n) => (n.id === activeNovel.id ? { ...n, chapters: remaining } : n)),
      );
      // 对话挂在小说名下，删一章不动它 —— 那一章的事还留在会话里，用户自己翻得到。
      if (chapter.id === activeChapterId) {
        const index = activeNovel.chapters.findIndex((c) => c.id === chapter.id);
        // 删掉当前章后优先落到后一章，没有则落到前一章
        const next = remaining[index] ?? remaining[index - 1] ?? null;
        setActiveChapterId(next?.id ?? null);
      }
    },
    [activeChapterId, activeNovel],
  );

  const handleContentChange = useCallback(
    (content: string) => {
      if (!activeNovelId || !activeChapterId) return;
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
    },
    [activeChapterId, activeNovelId],
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

  const handleSend = useCallback(
    (chapterId: string, text: string, attachments: InspirationItem[]) => {
      if (!activeNovelId || busy) return;
      // 对话挂在这本书名下，chapterId 只决定这一轮写 / 改的是哪一章（请求里照旧带上）。
      const threadId = activeNovelId;
      pushMessage(
        threadId,
        "user",
        text,
        attachments.length > 0 ? attachments : undefined,
      );

      // 这一轮先立起来，记在发起它的那一章名下：中途翻去别的章，稿子和进度都留在这儿。
      // 接着答上一轮的问题就复用现成的那一轮 —— 稿子留着，用户正对着它做决定。
      setActiveRun((prev) =>
        prev && prev.chapterId === chapterId
          ? { ...prev, stage: "", pendingQuestion: false }
          : { chapterId, draft: null, stage: "", pendingQuestion: false },
      );

      const handlers: NovelAgentHandlers = {
        onStage: (text) =>
          setActiveRun((prev) => (prev ? { ...prev, stage: text } : prev)),
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
          pushMessage(threadId, "assistant", question);
          setActiveRun((prev) =>
            prev
              ? {
                  ...prev,
                  draft: prev.draft ? { ...prev.draft, streaming: false } : null,
                  stage: "",
                  pendingQuestion: true,
                }
              : prev,
          );
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
      if (pendingQuestion) resume(activeNovelId, text, chapterId, handlers);
      else run(activeNovelId, text, chapterId, handlers);
    },
    [activeNovelId, busy, loadNovels, pendingQuestion, pushMessage, resume, run],
  );

  // 会话是整本书一条：切章时右侧不动，只有切书才换一份
  const messages = activeNovelId ? chats[activeNovelId] ?? [] : [];

  return (
    <div className={styles.shell}>
      {loadError && <div className={styles.notice}>{loadError}</div>}
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
        onSelectChapter={setActiveChapterId}
        onCreateChapter={handleCreateChapter}
        onRenameChapter={handleRenameChapter}
        onDeleteChapter={handleDeleteChapter}
        onChangeStatus={handleChapterStatusChange}
        onShowLedger={setLedgerChapter}
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
        pendingQuestion={pendingQuestion}
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
