"use client";

import "@ant-design/v5-patch-for-react-19";

import { useState, useEffect, useCallback } from "react";
import { Modal } from "antd";
import { BellOutlined } from "@ant-design/icons";
import type { getActiveAnnouncements } from "@/lib/server/announcements";
import styles from "./index.module.scss";

type AnnounceItem = Awaited<ReturnType<typeof getActiveAnnouncements>>[number];

export default function AnnouncementBanner({ announcements }: { announcements: AnnounceItem[] }) {
  const [current, setCurrent] = useState(0);
  const [selected, setSelected] = useState<AnnounceItem | null>(null);

  const total = announcements.length;
  if (total === 0) return null;

  const item = announcements[current];

  // 自动轮播
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrent((p) => (p + 1) % total);
    }, 5000);
    return () => clearInterval(timer);
  }, [total]);

  const goTo = useCallback((i: number) => setCurrent(i), []);

  const priorityLabel = (p: string) => {
    if (p === "urgent") return <span className={styles.labelUrgent}>紧急</span>;
    if (p === "high") return <span className={styles.labelHigh}>重要</span>;
    return null;
  };

  return (
    <>
      <div className={styles.banner}>
        <div className={styles.icon}>
          <BellOutlined style={{ fontSize: 15 }} />
          公告
        </div>

        <div className={styles.slideWrap}>
          <div className={styles.slide} key={item.id}>
            <span className={styles.slideTitle} onClick={() => setSelected(item)}>
              {priorityLabel(item.priority)}
              {item.title}
            </span>
            <span className={styles.slideContent} onClick={() => setSelected(item)}>
              {item.content.length > 80 ? item.content.slice(0, 80) + "…" : item.content}
            </span>
          </div>
        </div>

        {total > 1 && (
          <div className={styles.dots}>
            {announcements.map((a, i) => (
              <span
                key={a.id}
                className={`${styles.dot} ${i === current ? styles.dotActive : ""}`}
                onClick={() => goTo(i)}
              />
            ))}
          </div>
        )}
      </div>

      <Modal
        open={!!selected}
        onCancel={() => setSelected(null)}
        footer={null}
        width={560}
      >
        {selected && (
          <>
            <div className={styles.modalTitle}>{selected.title}</div>
            <div className={styles.modalMeta}>
              发布于 {selected.publishedAt ? new Date(selected.publishedAt).toLocaleString() : "-"}
            </div>
            <div className={styles.modalContent}>{selected.content}</div>
          </>
        )}
      </Modal>
    </>
  );
}