"use client";

import { useCallback, useRef } from "react";
import styles from "./index.module.scss";

interface EditableTitleProps {
  value: string;
  /** 只读态显示这个（章节列表窄，展示"第N章"即可）；编辑态与提交仍用完整 value */
  displayValue?: string;
  /** 由父级控制当前是否为编辑态，便于同一列表里只有一个标题处于编辑中 */
  editing: boolean;
  onCommit: (next: string) => void;
  onCancel: () => void;
  className?: string;
  /** 只读态被点了：给"点一下就改"的用法（章节栏头顶那行类型 / 文风）。编辑态不理会 */
  onClick?: () => void;
}

export default function EditableTitle({
  value,
  displayValue,
  editing,
  onCommit,
  onCancel,
  className,
  onClick,
}: EditableTitleProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  // 身份稳定，避免父级每次重渲染都重新聚焦全选打断输入
  const attachRef = useCallback((el: HTMLInputElement | null) => {
    inputRef.current = el;
    el?.select();
  }, []);

  if (!editing) {
    return (
      <span className={className} onClick={onClick}>
        {displayValue ?? value}
      </span>
    );
  }

  const commit = () => {
    const next = inputRef.current?.value.trim() ?? "";
    // 空标题视为放弃修改，避免列表里出现无名条目
    if (next && next !== value) onCommit(next);
    else onCancel();
  };

  return (
    <input
      ref={attachRef}
      className={`${styles.input} ${className ?? ""}`}
      defaultValue={value}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
        } else if (e.key === "Escape") {
          e.preventDefault();
          onCancel();
        }
      }}
      onBlur={commit}
      onClick={(e) => e.stopPropagation()}
    />
  );
}
