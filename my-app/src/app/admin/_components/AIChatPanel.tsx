"use client";

import {
  RobotOutlined, CloseOutlined, WechatOutlined,
} from "@ant-design/icons";
import styles from "../layout.module.scss";

export default function AIChatPanel({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: (v: boolean) => void;
}) {
  if (collapsed) {
    return (
      <div className={styles.aiPanelCollapsed}>
        <button className={styles.aiToggleBtn} onClick={() => onToggle(false)} title="打开 AI 运营助手">
          <RobotOutlined />
        </button>
      </div>
    );
  }

  return (
    <div className={styles.aiPanel}>
      <div className={styles.aiPanelHeader}>
        <span><RobotOutlined style={{ marginRight: 6 }} />AI 运营助手</span>
        <button className={styles.aiToggleBtn} onClick={() => onToggle(true)}>
          <CloseOutlined />
        </button>
      </div>
      <div className={styles.aiPanelBody}>
        <div className={styles.aiEmpty}>
          <WechatOutlined style={{ fontSize: 32, opacity: 0.3 }} />
          <p>暂无对话</p>
          <span>AI 运营助手功能开发中</span>
        </div>
      </div>
      <div className={styles.aiPanelFooter}>
        <input
          className={styles.aiInput}
          placeholder="输入消息..."
          disabled
        />
      </div>
    </div>
  );
}