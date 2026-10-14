"use client";

import { useMemo, useState } from "react";
import {
  AlignLeftOutlined,
  DeleteOutlined,
  FileTextOutlined,
  LinkOutlined,
  PictureOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import type {
  Chapter,
  InspirationCategory,
  InspirationItem,
  InspirationLifecycle,
  InspirationUsage,
} from "../types";
import {
  INSPIRATION_CATEGORY_LABEL,
  INSPIRATION_CATEGORY_OPTIONS,
  INSPIRATION_LIFECYCLE_LABEL,
  INSPIRATION_USAGE_LABEL,
  INSPIRATION_USAGE_OPTIONS,
} from "../types";
import InspirationModal from "../InspirationModal";
import { invalidateNovel, mutateNovel, useNovelQuery } from "../useNovelQuery";
import styles from "./index.module.scss";

interface InspirationRow {
  id: string;
  /** 同一份素材（一次新增）产出的多条灵感共享此 id；空串是老数据，各自成组 */
  sourceId: string;
  title: string;
  /** 内容类型（一条灵感归一个），驱动重新翻译 */
  category: string[];
  /** 素材形态：text / file / url（老数据可能是 image） */
  type: string;
  content: string;
  /** 使用策略：must 必用 / selectable 选用 / never 不用 */
  usage: string;
  /** 生命周期：reuse 复用 / once 单次 */
  lifecycle: string;
  /** 可使用场景（模型翻译产出） */
  scenario: string;
  /** 写作指引（模型翻译产出） */
  digest: string;
  usedChapterIds: string[];
}

interface InspirationsResponse {
  threadId: string;
  total: number;
  inspirations: InspirationRow[];
}

interface InspirationPanelProps {
  threadId: string | null;
  /** 这本书的章节，用来把 usedChapterIds 渲染成"第N章 标题"，并做章节筛选 */
  chapters: Chapter[];
}

const ALL = "all";

function FormIcon({ form }: { form: string }) {
  const cls = styles.formIcon;
  if (form === "image") return <PictureOutlined className={cls} />;
  if (form === "text") return <AlignLeftOutlined className={cls} />;
  if (form === "url") return <LinkOutlined className={cls} />;
  return <FileTextOutlined className={cls} />;
}

/** 没名字时拿内容头部兜底（老数据 title 为空），也当素材卡的标题用 */
function head(content: string, limit = 40) {
  const flat = content.replace(/\s+/g, " ").trim();
  if (!flat) return "（空素材）";
  return flat.length > limit ? `${flat.slice(0, limit)}…` : flat;
}

/** 一份素材的组键：同一 sourceId 归一组；老数据（空串）按各自 id 单独成组 */
function groupKey(row: InspirationRow) {
  return row.sourceId || row.id;
}

/** 一组灵感覆盖的全部标签（并集，保序）——素材卡上默认选中的就是它 */
function unionCats(rows: InspirationRow[]): string[] {
  const out: string[] = [];
  for (const row of rows) {
    for (const c of row.category ?? []) if (!out.includes(c)) out.push(c);
  }
  return out;
}

/** 一条灵感"是什么"：把它的标签翻成中文，摆在该条左侧 */
function catLabel(row: InspirationRow): string {
  const cats = row.category ?? [];
  if (cats.length === 0) return "其他";
  return cats
    .map((c) => INSPIRATION_CATEGORY_LABEL[c as InspirationCategory] ?? c)
    .join("、");
}

/**
 * 灵感库：这本书攒下的所有灵感（novel_inspiration）。
 *
 * **一份素材 = 一张卡**：一次新增按用户选的多个标签会产出多条灵感，它们共享 sourceId，这里并进
 * 同一张卡。标签（分类）挂在**素材**上（即"这份素材要做成哪几类灵感"），改完点重新翻译即按它重建；
 * 卡内每条灵感只在左侧标一下自己是什么。
 *
 * 左筛选项仍按单条灵感过滤；"使用/未使用"由 usedChapterIds 派生，由 writer/planner 引用后自动出现。
 */
export default function InspirationPanel({ threadId, chapters }: InspirationPanelProps) {
  const url = threadId
    ? `/api/novel/method/inspirations?threadId=${encodeURIComponent(threadId)}`
    : null;
  const { data, loading, error } = useNovelQuery<InspirationsResponse>(url);

  const [modalOpen, setModalOpen] = useState(false);
  const [category, setCategory] = useState<string>(ALL);
  const [keyword, setKeyword] = useState("");
  const [chapterId, setChapterId] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  // 素材卡上的标签选择（重新翻译按它重建）：组键 → 选中的标签；没动过就走该组现有标签的并集
  const [catDraft, setCatDraft] = useState<Record<string, string[]>>({});

  // 章节 id → "第N章 标题"；列表要给人看章节名，库里存的只是 cuid
  const chapterName = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of chapters) {
      const order = c.order ?? 0;
      map.set(c.id, c.title ? `第${order}章 ${c.title}` : `第${order}章`);
    }
    return map;
  }, [chapters]);

  const rows = data?.inspirations ?? [];
  const kw = keyword.trim().toLowerCase();
  const filtering = category !== ALL || chapterId !== "" || kw !== "";

  const filtered = rows.filter((row) => {
    const cats = row.category ?? [];
    if (category !== ALL && !cats.includes(category)) return false;
    if (chapterId && !row.usedChapterIds.includes(chapterId)) return false;
    if (kw && !`${row.title} ${row.content}`.toLowerCase().includes(kw)) return false;
    return true;
  });

  // 每份素材（组键）名下**全部**行的 id：重新翻译 / 删除都按整份素材来，不受筛选影响
  // （筛选只是看不看得到，不该把没显示的那几条漏在库里）。
  const idsByGroup = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const row of rows) {
      const key = groupKey(row);
      const arr = map.get(key);
      if (arr) arr.push(row.id);
      else map.set(key, [row.id]);
    }
    return map;
  }, [rows]);

  // 渲染用的分组：在筛过的行上按组键聚拢，保留原顺序
  const groups = useMemo(() => {
    const map = new Map<string, InspirationRow[]>();
    for (const row of filtered) {
      const key = groupKey(row);
      const arr = map.get(key);
      if (arr) arr.push(row);
      else map.set(key, [row]);
    }
    return [...map.entries()];
  }, [filtered]);

  // 新增一份素材（单素材 + 标签 / 使用策略）。**不在这里关弹窗**：交给弹窗等翻译落库完再关；
  // 失败就抛出，让弹窗自己报错（父级不再吞异常）。signal 来自弹窗——关窗时 abort，取消这趟翻译。
  const add = async (
    items: InspirationItem[],
    cats?: InspirationCategory[],
    usage?: InspirationUsage,
    signal?: AbortSignal,
  ) => {
    if (!threadId) throw new Error("请先选择小说");
    const form = new FormData();
    form.append("novelId", threadId);
    for (const c of cats ?? ["other"]) form.append("category", c);
    if (usage) form.append("usage", usage);
    form.append(
      "inspirations",
      JSON.stringify(
        items.map((a) => ({
          kind: a.kind,
          name: a.name,
          url: a.url ?? "",
          text: a.text ?? "",
          hasFile: Boolean(a.file),
        })),
      ),
    );
    for (const a of items) if (a.file) form.append("files", a.file);
    // 落库前后端要等模型翻译，默认 10s 会先一步断开、报"后端响应超时"；留 90s（后端模型侧 60s 兜底）。
    await mutateNovel("/api/novel/method/inspiration", {
      method: "POST",
      body: form,
      timeout: 90_000,
      signal,
    });
    invalidateNovel(threadId);
  };

  /** 就地改一条灵感的使用策略（不碰原文与译文；标签在素材卡上改，生命周期固定、改不了）。 */
  const patch = async (id: string, fields: { usage?: string }) => {
    if (!threadId || busyId) return;
    const form = new FormData();
    form.append("novelId", threadId);
    form.append("inspirationId", id);
    if (fields.usage) form.append("usage", fields.usage);
    else return;
    setBusyId(id);
    setActionError("");
    try {
      await mutateNovel("/api/novel/method/inspiration", { method: "PATCH", body: form });
      invalidateNovel(threadId);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "没能改掉");
    } finally {
      setBusyId(null);
    }
  };

  /** 素材卡上勾 / 取消一个标签（至少留一个；改完点重新翻译才重建）。 */
  const toggleCat = (key: string, value: string, groupRows: InspirationRow[]) => {
    const current = catDraft[key] ?? unionCats(groupRows);
    const next = current.includes(value)
      ? current.filter((c) => c !== value)
      : [...current, value];
    if (next.length === 0) return; // 一份素材至少留一个标签
    setCatDraft((prev) => ({ ...prev, [key]: next }));
  };

  /** 重新翻译一份素材：按素材卡上选的标签重跑模型，重建这份素材产出的灵感（缺的补、多的删）。 */
  const retranslate = async (key: string, ids: string[], cats: string[]) => {
    if (!threadId || busyId || ids.length === 0 || cats.length === 0) return;
    const form = new FormData();
    form.append("novelId", threadId);
    for (const id of ids) form.append("inspirationId", id);
    for (const c of cats) form.append("category", c);
    setBusyId(ids[0]);
    setActionError("");
    try {
      // 重新翻译同样要等模型出结果，别让 10s 的默认值先断开
      await mutateNovel("/api/novel/method/inspiration/translate", {
        method: "POST",
        body: form,
        timeout: 90_000,
      });
      // 重建完成，丢掉草稿让标签对齐刚落库的结果
      setCatDraft((prev) => {
        if (!(key in prev)) return prev;
        const next = { ...prev };
        delete next[key];
        return next;
      });
      invalidateNovel(threadId);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "没能重新翻译");
    } finally {
      setBusyId(null);
    }
  };

  /** 删掉一份素材产出的全部灵感（这组 id 一起删）。 */
  const remove = async (ids: string[]) => {
    if (!threadId || busyId || ids.length === 0) return;
    const qs = ids.map((id) => `inspirationId=${encodeURIComponent(id)}`).join("&");
    setBusyId(ids[0]);
    setActionError("");
    try {
      await mutateNovel(
        `/api/novel/method/inspiration?novelId=${encodeURIComponent(threadId)}&${qs}`,
        { method: "DELETE" },
      );
      invalidateNovel(threadId);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "没能删除");
    } finally {
      setBusyId(null);
    }
  };

  if (!threadId) return <div className={styles.hint}>请先在左侧选择小说</div>;

  return (
    <div className={styles.panel}>
      <div className={styles.topBar}>
        <span className={styles.summary}>
          共 {data?.total ?? 0} 条{filtering ? `（筛出 ${filtered.length} 条）` : ""}
        </span>
        <button type="button" className={styles.addBtn} onClick={() => setModalOpen(true)}>
          <PlusOutlined />
          <span>新增</span>
        </button>
      </div>

      {actionError ? <div className={styles.actionError}>{actionError}</div> : null}

      <div className={styles.controls}>
        <div className={styles.chipRow}>
          <button
            type="button"
            className={`${styles.chip} ${category === ALL ? styles.chipOn : ""}`}
            onClick={() => setCategory(ALL)}
          >
            全部
          </button>
          {INSPIRATION_CATEGORY_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`${styles.chip} ${category === option.value ? styles.chipOn : ""}`}
              onClick={() => setCategory(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className={styles.filters}>
          <input
            className={styles.filterInput}
            placeholder="关键字"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          <select
            className={styles.filterInput}
            value={chapterId}
            onChange={(e) => setChapterId(e.target.value)}
          >
            <option value="">全部章节</option>
            {chapters.map((c) => (
              <option key={c.id} value={c.id}>
                {chapterName.get(c.id)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <div className={styles.hint}>加载中…</div>
      ) : error ? (
        <div className={styles.hint}>加载失败：{error}</div>
      ) : rows.length === 0 ? (
        <div className={styles.hint}>
          这本书还没有灵感。点右上角“新增”，把风格、剧情、热梗这类想法攒进来。
        </div>
      ) : filtered.length === 0 ? (
        <div className={styles.hint}>没有匹配的灵感</div>
      ) : (
        <div className={styles.cards}>
          {groups.map(([key, groupRows]) => {
            const first = groupRows[0];
            const ids = idsByGroup.get(key) ?? groupRows.map((r) => r.id);
            const cats = catDraft[key] ?? unionCats(groupRows);
            return (
              <article key={key} className={styles.card}>
                {/* 素材头：左上角是素材原文的标题，右侧重新翻译 / 删除整份素材 */}
                <div className={styles.sourceHead}>
                  <FormIcon form={first.type} />
                  <div className={styles.sourceText}>
                    <span className={styles.sourceTitle} title={first.content}>
                      {head(first.content)}
                    </span>
                    <span className={styles.sourceContent}>{first.content || "（空素材）"}</span>
                  </div>
                  <div className={styles.sourceActions}>
                    <button
                      type="button"
                      className={styles.iconBtn}
                      disabled={busyId !== null}
                      onClick={() => retranslate(key, ids, cats)}
                      title="按下面选的标签重新翻译这份素材"
                      aria-label="重新翻译"
                    >
                      <ReloadOutlined />
                    </button>
                    <button
                      type="button"
                      className={styles.deleteBtn}
                      disabled={busyId !== null}
                      onClick={() => remove(ids)}
                      title="删除这份素材产出的全部灵感"
                      aria-label="删除"
                    >
                      <DeleteOutlined />
                    </button>
                  </div>
                </div>

                {/* 素材级标签：这份素材要做成哪几类灵感；改完点右上角重新翻译重建 */}
                <div className={styles.catRow}>
                  {INSPIRATION_CATEGORY_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={`${styles.catChip} ${
                        cats.includes(option.value) ? styles.catChipOn : ""
                      }`}
                      disabled={busyId !== null}
                      onClick={() => toggleCat(key, option.value, groupRows)}
                      title="改标签（改完点重新翻译生效）"
                    >
                      {option.label}
                    </button>
                  ))}
                </div>

                {/* 这份素材产出的各条灵感：一条一个子块，左侧只标一下它是什么 */}
                <div className={styles.inspList}>
                  {groupRows.map((row) => {
                    const usedLabels = row.usedChapterIds
                      .map((id) => chapterName.get(id))
                      .filter(Boolean)
                      .join("、");
                    return (
                      <div key={row.id} className={styles.inspBlock}>
                        <div className={styles.inspHead}>
                          <span className={styles.inspCat}>{catLabel(row)}</span>
                          <span className={styles.inspTitle} title={row.title || row.content}>
                            {row.title || head(row.content)}
                          </span>
                          {/* 使用策略：右上角下拉框，就地切必用 / 选用 / 不用 */}
                          <select
                            className={`${styles.usageSelect} ${styles[`usage_${row.usage}`] ?? ""}`}
                            value={row.usage}
                            disabled={busyId !== null}
                            onChange={(e) => patch(row.id, { usage: e.target.value })}
                            title="使用策略"
                            aria-label="使用策略"
                          >
                            {INSPIRATION_USAGE_OPTIONS.map((option) => (
                              <option key={option.value} value={option.value}>
                                {INSPIRATION_USAGE_LABEL[option.value]}
                              </option>
                            ))}
                          </select>
                        </div>

                        {row.scenario ? (
                          <div className={styles.cardField}>
                            <span className={styles.fieldLabel}>场景</span>
                            <span className={styles.fieldValue}>{row.scenario}</span>
                          </div>
                        ) : null}
                        {row.digest ? (
                          <div className={styles.cardField}>
                            <span className={styles.fieldLabel}>写作指引</span>
                            <span className={styles.fieldValue}>{row.digest}</span>
                          </div>
                        ) : null}

                        <div className={styles.cardFoot}>
                          {row.usedChapterIds.length > 0 ? (
                            <span className={styles.usedTag}>
                              已用于{usedLabels ? ` ${usedLabels}` : ""}
                            </span>
                          ) : (
                            <span className={styles.unusedTag}>未使用</span>
                          )}
                          {/* 生命周期固定、不能改：按标签自动定，右下角只读展示 */}
                          <span className={styles.lifeTag} title="按标签自动定，不可改">
                            {INSPIRATION_LIFECYCLE_LABEL[
                              row.lifecycle as InspirationLifecycle
                            ] ?? row.lifecycle}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {modalOpen && (
        <InspirationModal
          single
          allowImage={false}
          allowText
          showCategory
          title="新增灵感"
          onClose={() => setModalOpen(false)}
          onConfirm={add}
        />
      )}
    </div>
  );
}