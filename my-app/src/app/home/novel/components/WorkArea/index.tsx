"use client";

import type { ComponentType } from "react";
import {
  AlertOutlined,
  AppstoreOutlined,
  BranchesOutlined,
  BulbOutlined,
  ExportOutlined,
  FileTextOutlined,
  GiftOutlined,
  GlobalOutlined,
  HistoryOutlined,
  ReadOutlined,
  ShareAltOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import ChapterBody from "../ChapterBody";
import ImpactsPanel from "../ImpactsPanel";
import SettingPanel from "../SettingPanel";
import { PANEL_SPECS } from "../SettingPanel/specs";
import type {
  Chapter,
  ChapterStatus,
  InspirationItem,
  Message,
  RunChapter,
  WorkTab,
} from "../types";
import styles from "./index.module.scss";

const WORK_TABS: {
  key: WorkTab;
  label: string;
  Icon: ComponentType<{ className?: string }>;
}[] = [
  { key: "text", label: "正文", Icon: FileTextOutlined },
  { key: "outline", label: "小说大纲", Icon: ReadOutlined },
  { key: "characters", label: "人物档案", Icon: TeamOutlined },
  { key: "world", label: "世界观", Icon: GlobalOutlined },
  { key: "timeline", label: "世界线", Icon: BranchesOutlined },
  { key: "factions", label: "势力阵营", Icon: AppstoreOutlined },
  { key: "chronicle", label: "编年史", Icon: HistoryOutlined },
  { key: "items", label: "物品设定", Icon: GiftOutlined },
  { key: "relations", label: "关系图", Icon: ShareAltOutlined },
  { key: "inspiration", label: "灵感库", Icon: BulbOutlined },
  { key: "export", label: "全书导出", Icon: ExportOutlined },
  { key: "impacts", label: "受影响点", Icon: AlertOutlined },
];

interface WorkAreaProps {
  tab: WorkTab;
  onTabChange: (tab: WorkTab) => void;
  /** 当前这本书的 id（也就是会话 threadId），各标签页照着它去库里取数 */
  threadId: string | null;
  chapter: Chapter | null;
  onContentChange: (content: string) => void;
  /** 改当前这一章的状态（完成 / 草稿 / 待修复），落库 */
  onChangeStatus: (status: ChapterStatus) => void;
  messages: Message[];
  onSend: (text: string, attachments: InspirationItem[]) => void;
  /** 正在流式生成的那一稿，正文区显示它、盖住这一章原有的内容 */
  draft: { content: string; streaming: boolean } | null;
  /** 状态行文案 */
  stage: string;
  /** 这一章的对话面板整个封掉：本轮还没跑完，或本轮在别的章上跑 */
  chatDisabled: boolean;
  /** 这一轮的流还开着（能掐断） */
  running: boolean;
  /** 掐断这一轮生成 */
  onStop: () => void;
  /** 图在等用户答复（收下这一稿 / 说往哪儿改） */
  pendingQuestion: boolean;
  /** 停在确认上时后端给的出口按钮（收下 / 按库里改） */
  answerOptions: { id: string; label: string }[];
  onAnswer: (option: { id: string; label: string }) => void;
  /** 清空这本的对话记录（后端那份一起清，刷新后不会回来） */
  onClear: () => void;
  /** 本轮正在生成的那一章，写在正文区标题栏右边；null = 没有在跑的 */
  runChapter: RunChapter | null;
}

export default function WorkArea({
  tab,
  onTabChange,
  threadId,
  chapter,
  onContentChange,
  onChangeStatus,
  messages,
  onSend,
  draft,
  stage,
  chatDisabled,
  running,
  onStop,
  pendingQuestion,
  answerOptions,
  onAnswer,
  onClear,
  runChapter,
}: WorkAreaProps) {
  const activeTab = WORK_TABS.find((t) => t.key === tab) ?? WORK_TABS[0];
  const ActiveIcon = activeTab.Icon;

  return (
    <main className={styles.area}>
      <div className={styles.tabBar}>
        {WORK_TABS.map(({ key, label, Icon }) => (
          <button
            key={key}
            type="button"
            className={`${styles.tab} ${key === tab ? styles.tabActive : ""}`}
            onClick={() => onTabChange(key)}
          >
            <Icon className={styles.tabIcon} />
            <span>{label}</span>
          </button>
        ))}
      </div>

      <div className={styles.content}>
        {tab === "text" ? (
          chapter ? (
            <ChapterBody
              chapter={chapter}
              onContentChange={onContentChange}
              onChangeStatus={onChangeStatus}
              messages={messages}
              onSend={onSend}
              draft={draft}
              stage={stage}
              chatDisabled={chatDisabled}
              running={running}
              onStop={onStop}
              pendingQuestion={pendingQuestion}
              answerOptions={answerOptions}
              onAnswer={onAnswer}
              onClear={onClear}
              runChapter={runChapter}
            />
          ) : (
            <div className={styles.placeholder}>
              <FileTextOutlined className={styles.placeholderIcon} />
              <div className={styles.placeholderTitle}>尚未选择章节</div>
              <div className={styles.placeholderDesc}>
                从左侧章节列表选择一章，或点 + 新建章节
              </div>
            </div>
          )
        ) : tab === "impacts" ? (
          <ImpactsPanel threadId={threadId} />
        ) : PANEL_SPECS[tab] ? (
          // 一个按钮一个口子：这张表里没有的就是还没有库表支撑的（导出是前端自己拼的）
          <SettingPanel threadId={threadId} spec={PANEL_SPECS[tab]!} />
        ) : (
          <div className={styles.placeholder}>
            <ActiveIcon className={styles.placeholderIcon} />
            <div className={styles.placeholderTitle}>{activeTab.label}</div>
            <div className={styles.placeholderDesc}>该功能正在开发中</div>
          </div>
        )}
      </div>
    </main>
  );
}
