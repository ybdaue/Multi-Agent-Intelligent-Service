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

function formatTime(value: string) {
  const time = new Date(value);
  return Number.isNaN(time.getTime()) ? "" : time.toLocaleString("zh-CN");
}

export default function ImpactsPanel({ threadId }: { threadId: string | null }) {
  const url = threadId
    ? `/api/novel/method/impacts?threadId=${encodeURIComponent(threadId)}`
    : null;
  const { data, loading, error } = useNovelQuery<ImpactsResponse>(url);
  /** 正在改的那一条（同时挡住连点），null 表示没有在飞的 */
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");

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

  return (
    <div className={styles.panel}>
      <div className={styles.summary}>
        共 {data?.total ?? 0} 处可能受影响的点，按改动分成 {changes.length} 批
      </div>
      {actionError ? <div className={styles.actionError}>{actionError}</div> : null}

      <div className={styles.groups}>
        {changes.map((change) => (
          <section key={change.changeId} className={styles.group}>
            <header className={styles.groupHeader}>
              <span className={styles.groupTitle}>{change.changeSummary}</span>
              <span className={styles.groupMeta}>
                改的是{change.sourceTypeLabel} · {formatTime(change.createdAt)} · 波及{" "}
                {change.total} 处
              </span>
            </header>

            <ul className={styles.items}>
              {change.items.map((item) => (
                <li key={item.id} className={styles.item}>
                  <AlertOutlined
                    className={`${styles.itemIcon} ${styles[item.severity] ?? ""}`}
                  />
                  <div className={styles.itemBody}>
                    <div className={styles.itemHead}>
                      <span className={styles.target}>
                        {item.targetTypeLabel}
                        {item.targetChapter != null ? ` · 第 ${item.targetChapter} 章` : ""}
                      </span>
                      <span className={`${styles.chip} ${styles[item.severity] ?? ""}`}>
                        {SEVERITY_LABELS[item.severity] ?? item.severity}
                      </span>
                      <span className={styles.status}>
                        {STATUS_LABELS[item.status] ?? item.status}
                      </span>
                    </div>
                    <div className={styles.reason}>{item.reason}</div>
                    {item.resolution ? (
                      <div className={styles.resolution}>处理：{item.resolution}</div>
                    ) : null}
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
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
