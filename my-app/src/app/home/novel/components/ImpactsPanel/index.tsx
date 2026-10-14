"use client";

import { AlertOutlined } from "@ant-design/icons";
import { useState } from "react";
import { invalidateNovel, mutateNovel, useNovelQuery } from "../useNovelQuery";
import styles from "./index.module.scss";

interface ImpactItem {
  id: string;
  targetType: string;
  targetTypeLabel: string;
  targetId: string;
  targetChapter: number | null;
  reasonKind: string;
  reason: string;
  severity: string;
  status: string;
  resolution: string;
  oldValue: string;
  newValue: string;
  detectedBy: string;
}

interface ImpactChange {
  changeId: string;
  changeSummary: string;
  sourceType: string;
  sourceTypeLabel: string;
  sourceId: string;
  createdAt: string;
  total: number;
  items: ImpactItem[];
}

interface ImpactsResponse {
  threadId: string;
  total: number;
  changes: ImpactChange[];
}

// 库里存的是枚举值，说成人话是前端的事（后端只把类型名换成了中文标签）。
const SEVERITY_LABELS: Record<string, string> = {
  must_fix: "必改",
  review: "待定",
  info: "参考",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "未处理",
  accepted: "已接受",
  skipped: "已跳过",
  fixed: "已修复",
};

// 能点的三个出口。不给"退回未处理"：他要是改主意了，再点另一个档就是了。
const ACTIONS: { value: string; label: string }[] = [
  { value: "accepted", label: "接受" },
  { value: "skipped", label: "跳过" },
  { value: "fixed", label: "已修" },
];

/** 「按章节」视图里同一章下的排序档：必改在前。认不出的排到末尾。 */
const SEVERITY_ORDER: Record<string, number> = { must_fix: 0, review: 1, info: 2 };
/** 没挂章节的行（改动波及的不是某一章）在「按章节」视图里归到这一桶，排最后。 */
const NO_CHAPTER = "未关联章节";

function formatTime(value: string) {
  const time = new Date(value);
  return Number.isNaN(time.getTime()) ? "" : time.toLocaleString("zh-CN");
}

type ImpactPair = { change: ImpactChange; item: ImpactItem };

export default function ImpactsPanel({ threadId }: { threadId: string | null }) {
  const url = threadId
    ? `/api/novel/method/impacts?threadId=${encodeURIComponent(threadId)}`
    : null;
  const { data, loading, error } = useNovelQuery<ImpactsResponse>(url);
  /** 正在改的那一条（同时挡住连点），null 表示没有在飞的 */
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  /** 两种排版：按改动产生的时间分组，或按波及到的章节分组 */
  const [view, setView] = useState<"time" | "chapter">("time");
  const [keyword, setKeyword] = useState("");
  const [chapterFilter, setChapterFilter] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  // 标一处受影响点；落库成功了就把这一本书的缓存标陈旧，面板自己重拉那一份 —— 不手写本地 patch。
  const mark_impact = async (impactId: string, status: string) => {
    if (!threadId || busyId) return;
    const form = new FormData();
    form.append("novelId", threadId);
    form.append("impactId", impactId);
    form.append("status", status);
    setBusyId(impactId);
    setActionError("");
    try {
      await mutateNovel("/api/novel/method/impact/status", { method: "POST", body: form });
      invalidateNovel(threadId);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "没能改掉");
    } finally {
      setBusyId(null);
    }
  };

  if (!threadId) return <div className={styles.hint}>请先在左侧选择小说</div>;
  if (loading) return <div className={styles.hint}>加载中…</div>;
  if (error) return <div className={styles.hint}>加载失败：{error}</div>;

  const changes = data?.changes ?? [];
  if (changes.length === 0) {
    return <div className={styles.hint}>这本书还没有改动记录</div>;
  }

  // 过滤条件：关键词匹配改动描述 / 原因 / 波及类型，章节号精确匹配，日期取改动产生那天。
  const kw = keyword.trim().toLowerCase();
  const chapRaw = chapterFilter.trim();
  const chap = /^\d+$/.test(chapRaw) ? Number(chapRaw) : null;
  const fromTs = fromDate ? new Date(`${fromDate}T00:00:00`).getTime() : null;
  const toTs = toDate ? new Date(`${toDate}T23:59:59`).getTime() : null;

  const pairs: ImpactPair[] = changes.flatMap((change) =>
    change.items
      .filter((item) => {
        if (kw) {
          const hay = `${change.changeSummary} ${item.reason} ${item.targetTypeLabel}`.toLowerCase();
          if (!hay.includes(kw)) return false;
        }
        if (chap !== null && item.targetChapter !== chap) return false;
        if (fromTs !== null || toTs !== null) {
          const ts = new Date(change.createdAt).getTime();
          if (Number.isNaN(ts)) return false;
          if (fromTs !== null && ts < fromTs) return false;
          if (toTs !== null && ts > toTs) return false;
        }
        return true;
      })
      .map((item) => ({ change, item })),
  );

  const filtered = kw || chap !== null || fromDate || toDate;

  // 按时间：沿用改动分组，丢掉筛空的组。
  const timeGroups = changes
    .map((change) => ({
      change,
      items: pairs.filter((p) => p.change.changeId === change.changeId).map((p) => p.item),
    }))
    .filter((group) => group.items.length > 0);

  // 按章节：同一章归一组，章序升序，未关联章节排最后；同章内必改在前。
  const chapterMap = new Map<number | null, ImpactItem[]>();
  for (const { item } of pairs) {
    const key = item.targetChapter ?? null;
    const arr = chapterMap.get(key) ?? [];
    arr.push(item);
    chapterMap.set(key, arr);
  }
  const chapterGroups = [...chapterMap.entries()]
    .sort((a, b) => {
      if (a[0] === null) return 1;
      if (b[0] === null) return -1;
      return a[0] - b[0];
    })
    .map(([chapter, items]) => ({
      key: chapter === null ? NO_CHAPTER : `第 ${chapter} 章`,
      items: [...items].sort(
        (a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9),
      ),
    }));

  const renderItem = (item: ImpactItem) => (
    <li key={item.id} className={styles.item}>
      <AlertOutlined className={`${styles.itemIcon} ${styles[item.severity] ?? ""}`} />
      <div className={styles.itemBody}>
        <div className={styles.itemHead}>
          <span className={styles.target}>
            {item.targetTypeLabel}
            {item.targetChapter != null ? ` · 第 ${item.targetChapter} 章` : ""}
          </span>
          <span className={`${styles.chip} ${styles[item.severity] ?? ""}`}>
            {SEVERITY_LABELS[item.severity] ?? item.severity}
          </span>
          <span className={styles.status}>{STATUS_LABELS[item.status] ?? item.status}</span>
        </div>
        <div className={styles.reason}>{item.reason}</div>
        {item.resolution ? <div className={styles.resolution}>处理：{item.resolution}</div> : null}
        <div className={styles.actions}>
          {ACTIONS.map((action) => (
            <button
              key={action.value}
              type="button"
              className={styles.action}
              disabled={busyId !== null || item.status === action.value}
              onClick={() => mark_impact(item.id, action.value)}
            >
              {action.label}
            </button>
          ))}
        </div>
      </div>
    </li>
  );

  return (
    <div className={styles.panel}>
      <div className={styles.summary}>
        共 {data?.total ?? 0} 处可能受影响的点{filtered ? `（当前筛出 ${pairs.length} 处）` : ""}
      </div>
      {actionError ? <div className={styles.actionError}>{actionError}</div> : null}

      <div className={styles.controls}>
        <div className={styles.viewSwitch}>
          <button
            type="button"
            className={`${styles.viewBtn} ${view === "time" ? styles.activeView : ""}`}
            onClick={() => setView("time")}
          >
            按时间
          </button>
          <button
            type="button"
            className={`${styles.viewBtn} ${view === "chapter" ? styles.activeView : ""}`}
            onClick={() => setView("chapter")}
          >
            按章节
          </button>
        </div>
        <div className={styles.filters}>
          <input
            className={styles.filterInput}
            placeholder="关键词"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          <input
            className={styles.filterInput}
            placeholder="章节号"
            inputMode="numeric"
            value={chapterFilter}
            onChange={(e) => setChapterFilter(e.target.value)}
          />
          <input
            className={styles.filterInput}
            type="date"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
          />
          <span className={styles.rangeSep}>~</span>
          <input
            className={styles.filterInput}
            type="date"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
          />
        </div>
      </div>

      {pairs.length === 0 ? (
        <div className={styles.hint}>没有匹配的受影响点</div>
      ) : view === "time" ? (
        <div className={styles.groups}>
          {timeGroups.map((group) => (
            <section key={group.change.changeId} className={styles.group}>
              <header className={styles.groupHeader}>
                <span className={styles.groupTitle}>{group.change.changeSummary}</span>
                <span className={styles.groupMeta}>
                  改的是{group.change.sourceTypeLabel} · {formatTime(group.change.createdAt)} · 波及{" "}
                  {group.items.length} 处
                </span>
              </header>
              <ul className={styles.items}>{group.items.map(renderItem)}</ul>
            </section>
          ))}
        </div>
      ) : (
        <div className={styles.groups}>
          {chapterGroups.map((group) => (
            <section key={group.key} className={styles.group}>
              <header className={styles.groupHeader}>
                <span className={styles.groupTitle}>{group.key}</span>
                <span className={styles.groupMeta}>波及 {group.items.length} 处</span>
              </header>
              <ul className={styles.items}>{group.items.map(renderItem)}</ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
