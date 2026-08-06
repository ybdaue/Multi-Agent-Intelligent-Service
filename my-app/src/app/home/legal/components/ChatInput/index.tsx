"use client";

import { useEffect, useRef } from "react";
import {
  PlusOutlined,
  SendOutlined,
  FileTextOutlined,
  CloseOutlined,
} from "@ant-design/icons";
import type { Attachment } from "../types";
import styles from "./index.module.scss";

const ACCEPTED_EXTENSIONS =
  ".pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.webp,.gif";
const MAX_ATTACHMENTS = 1;

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  attachments: Attachment[];
  onAddAttachment: (file: File) => void;
  onRemoveAttachment: (id: string) => void;
  disabled?: boolean;
  loading?: boolean;
}

export default function ChatInput({
  value,
  onChange,
  onSend,
  attachments,
  onAddAttachment,
  onRemoveAttachment,
  disabled = false,
  loading = false,
}: ChatInputProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const canSend = !loading && (value.trim().length > 0 || attachments.length > 0);

  useEffect(() => {
    const el = textareaRef.current;
    if (el && value === "") {
      el.style.height = "auto";
    }
  }, [value]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    onChange(e.target.value);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onAddAttachment(file);
    e.target.value = "";
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) onSend();
    }
  };

  return (
    <div className={styles.composer}>
      {attachments.length > 0 && (
        <div className={styles.attachmentList}>
          {attachments.map((a) => (
            <div key={a.id} className={styles.attachmentChip}>
              <FileTextOutlined />
              <span className={styles.attachmentName}>{a.name}</span>
              <button
                className={styles.removeBtn}
                onClick={() => onRemoveAttachment(a.id)}
                title="移除文件"
              >
                <CloseOutlined />
              </button>
            </div>
          ))}
          <span className={styles.limitHint}>
            最多上传 {MAX_ATTACHMENTS} 个文件
          </span>
        </div>
      )}

      <div className={styles.inputBox}>
        <button
          className={styles.attachBtn}
          onClick={() => fileInputRef.current?.click()}
          title="上传文件"
          disabled={disabled || loading || attachments.length >= MAX_ATTACHMENTS}
        >
          <PlusOutlined />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          hidden
          accept={ACCEPTED_EXTENSIONS}
          onChange={handleFileChange}
        />

        <textarea
          ref={textareaRef}
          className={styles.textarea}
          value={value}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          placeholder="请输入您的问题，Enter 发送，Shift+Enter 换行"
          rows={1}
          disabled={disabled}
        />

        <button
          className={styles.sendBtn}
          onClick={onSend}
          disabled={!canSend}
          title="发送"
        >
          <SendOutlined />
        </button>
      </div>
    </div>
  );
}
