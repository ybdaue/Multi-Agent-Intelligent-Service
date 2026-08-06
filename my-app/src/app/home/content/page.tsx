"use client";

import { Suspense, useState } from "react";
import styles from "./content.module.scss";
import AIChat from "./components/ai-chat";
import AIImage from "./components/ai-image";
import AIVideo from "./components/ai-video";

type Tab = "chat" | "image" | "video";

const tabs: { key: Tab; label: string; icon: string; disabled: boolean }[] = [
  { key: "chat", label: "AI 对话", icon: "AI", disabled: false },
  { key: "image", label: "AI 图片", icon: "IM", disabled: true },
  { key: "video", label: "AI 视频", icon: "VD", disabled: true },
];

export default function ContentPage() {
  const [activeTab, setActiveTab] = useState<Tab>("chat");

  return (
    <div className={styles.page}>
      <div className={styles.tabs}>
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`${styles.tab} ${activeTab === tab.key ? styles.tabActive : ""} ${tab.disabled ? styles.tabDisabled : ""}`}
            onClick={() => !tab.disabled && setActiveTab(tab.key)}
            disabled={tab.disabled}
          >
            <span className={styles.tabIcon}>{tab.icon}</span>
            <span>{tab.label}</span>
            {tab.disabled && <span className={styles.comingBadge}>即将上线</span>}
          </button>
        ))}
      </div>

      <Suspense fallback={null}>
        {activeTab === "chat" && <AIChat />}
        {activeTab === "image" && <AIImage />}
        {activeTab === "video" && <AIVideo />}
      </Suspense>
    </div>
  );
}
