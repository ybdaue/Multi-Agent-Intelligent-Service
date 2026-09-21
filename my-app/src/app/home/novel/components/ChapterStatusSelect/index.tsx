"use client";

import { useEffect, useRef, useState } from "react";
import { DownOutlined } from "@ant-design/icons";
import { CHAPTER_STATUS_LABEL, CHAPTER_STATUS_OPTIONS, type ChapterStatus } from "../types";
import styles from "./index.module.scss";

interface ChapterStatusSelectProps {
  value: ChapterStatus;
  /** 选中的一档与当前不同才会回调；提交中要拦一下连点 */
  onChange: (status: ChapterStatus) => void;
  disabled?: boolean;
  /** 章节列表里那一版：只出一个朝下的箭头 */
  compact?: boolean;
}

/** 菜单宽高写死：只有三档，且要据此决定往上还是往下弹，量不出来就先估 */
const MENU_WIDTH = 88;
const MENU_HEIGHT = 3 * 26 + 8;

/**
 * 给一章挑状态：完成 / 草稿 / 待修复。
 *
 * 自己写而不是拿现成组件：正文标题栏与章节列表两处形状差得多（一个有字一个只有箭头），
 * 而这一层依赖里根本没有组件库（@ant-design/icons 只有图标）。
 *
 * 菜单用 fixed 定位：章节列表是个 overflow-y: auto 的滚动容器，absolute 弹出去会被它裁掉，
 * 排在下半屏的那几章就点不着了。代价是滚动时它不会跟着走，所以一滚就关掉。
 */
export default function ChapterStatusSelect({
  value,
  onChange,
  disabled,
  compact,
}: ChapterStatusSelectProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const rootRef = useRef<HTMLSpanElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onDocDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  const toggle = (e: React.MouseEvent) => {
    // 章节列表里这一行整行可点（点一下切章）：别把选状态当成切章
    e.stopPropagation();
    if (open) {
      setOpen(false);
      return;
    }
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const below = rect.bottom + 4;
    const up = rect.top - MENU_HEIGHT - 4;
    // 贴着下沿就往上弹，弹不下再退回来贴下沿
    const top = below + MENU_HEIGHT > window.innerHeight && up > 4 ? up : below;
    setPos({
      top,
      left: Math.max(8, Math.min(rect.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8)),
    });
    setOpen(true);
  };

  return (
    <span className={styles.wrap} ref={rootRef}>
      <button
        type="button"
        ref={triggerRef}
        className={`${styles.trigger} ${compact ? styles.compact : ""}`}
        disabled={disabled}
        title="设置章节状态"
        aria-label="设置章节状态"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggle}
      >
        <DownOutlined />
      </button>
      {open && pos && (
        <div
          className={styles.menu}
          style={{ top: pos.top, left: pos.left, width: MENU_WIDTH }}
          role="menu"
        >
          {CHAPTER_STATUS_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="menuitemradio"
              aria-checked={option.value === value}
              className={`${styles.item} ${option.value === value ? styles.itemActive : ""}`}
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                if (option.value !== value) onChange(option.value);
              }}
            >
              <span className={`${styles.dot} ${styles[option.value]}`} />
              {CHAPTER_STATUS_LABEL[option.value]}
            </button>
          ))}
        </div>
      )}
    </span>
  );
}
