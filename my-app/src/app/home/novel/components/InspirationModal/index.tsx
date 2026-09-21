"use client";

import { useEffect, useRef, useState } from "react";
import {
  CloseOutlined,
  FileTextOutlined,
  LinkOutlined,
  PictureOutlined,
} from "@ant-design/icons";
import type { InspirationItem } from "../types";
import styles from "./index.module.scss";

interface InspirationModalProps {
  onClose: () => void;
  onConfirm: (items: InspirationItem[]) => void;
}

let seq = 0;
function createId() {
  seq += 1;
  return `insp-${Date.now().toString(36)}-${seq}`;
}

/** 图片读成 data URL，省去 object URL 的创建/回收生命周期 */
function toDataUrl(file: File): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => resolve("");
    reader.readAsDataURL(file);
  });
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function InspirationModal({
  onClose,
  onConfirm,
}: InspirationModalProps) {
  const [items, setItems] = useState<InspirationItem[]>([]);
  const [urlInput, setUrlInput] = useState("");
  const imageInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const addImages = async (files: FileList) => {
    const picked = await Promise.all(
      Array.from(files).map(async (file) => ({
        id: createId(),
        kind: "image" as const,
        name: file.name,
        size: file.size,
        file,
        preview: await toDataUrl(file),
      })),
    );
    setItems((prev) => [...prev, ...picked]);
  };

  const addFiles = (files: FileList) => {
    setItems((prev) => [
      ...prev,
      ...Array.from(files).map((file) => ({
        id: createId(),
        kind: "file" as const,
        name: file.name,
        size: file.size,
        file,
      })),
    ]);
  };

  const addUrl = () => {
    const raw = urlInput.trim();
    if (!raw) return;
    // 用户常只粘贴域名，缺协议时补上，避免生成不可点的链接
    const url = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
    setItems((prev) => [
      ...prev,
      { id: createId(), kind: "url", name: url, url },
    ]);
    setUrlInput("");
  };

  const remove = (id: string) => {
    setItems((prev) => prev.filter((i) => i.id !== id));
  };

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label="添加灵感素材"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.header}>
          <span className={styles.title}>添加灵感素材</span>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            title="关闭"
            aria-label="关闭"
          >
            <CloseOutlined />
          </button>
        </div>

        <div className={styles.body}>
          <div className={styles.pickers}>
            <button
              type="button"
              className={styles.pickBtn}
              onClick={() => imageInputRef.current?.click()}
            >
              <PictureOutlined />
              <span>上传图片</span>
            </button>
            <button
              type="button"
              className={styles.pickBtn}
              onClick={() => fileInputRef.current?.click()}
            >
              <FileTextOutlined />
              <span>上传文件</span>
            </button>
            <input
              ref={imageInputRef}
              type="file"
              accept="image/*"
              multiple
              hidden
              onChange={(e) => {
                if (e.target.files?.length) void addImages(e.target.files);
                e.target.value = "";
              }}
            />
            <input
              ref={fileInputRef}
              type="file"
              multiple
              hidden
              onChange={(e) => {
                if (e.target.files?.length) addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          <div className={styles.urlRow}>
            <input
              className={styles.urlInput}
              value={urlInput}
              placeholder="粘贴链接，如 example.com/article"
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addUrl();
                }
              }}
            />
            <button
              type="button"
              className={styles.addUrlBtn}
              onClick={addUrl}
              disabled={!urlInput.trim()}
            >
              添加
            </button>
          </div>

          <div className={styles.listWrap}>
            {items.length === 0 ? (
              <div className={styles.emptyHint}>
                还没有素材，可上传图片、文件或添加链接
              </div>
            ) : (
              <ul className={styles.list}>
                {items.map((item) => (
                  <li key={item.id} className={styles.item}>
                    {item.kind === "image" ? (
                      item.preview ? (
                        // eslint-disable-next-line @next/next/no-img-element -- data URL 本地预览，无远程加载可优化
                        <img className={styles.thumb} src={item.preview} alt="" />
                      ) : (
                        <PictureOutlined className={styles.itemIcon} />
                      )
                    ) : item.kind === "file" ? (
                      <FileTextOutlined className={styles.itemIcon} />
                    ) : (
                      <LinkOutlined className={styles.itemIcon} />
                    )}
                    <span className={styles.itemName} title={item.name}>
                      {item.name}
                    </span>
                    {item.kind === "file" && item.size != null && (
                      <span className={styles.itemMeta}>
                        {formatSize(item.size)}
                      </span>
                    )}
                    <button
                      type="button"
                      className={styles.removeBtn}
                      onClick={() => remove(item.id)}
                      title="移除"
                      aria-label="移除"
                    >
                      <CloseOutlined />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className={styles.footer}>
          <button type="button" className={styles.cancelBtn} onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className={styles.confirmBtn}
            onClick={() => onConfirm(items)}
            disabled={items.length === 0}
          >
            确定
          </button>
        </div>
      </div>
    </div>
  );
}
