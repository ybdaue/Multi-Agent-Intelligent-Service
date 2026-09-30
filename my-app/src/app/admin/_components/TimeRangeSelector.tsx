"use client";

import { Select } from "antd";
import type { TimeContext, TimeRange } from "../types/dashboard";
import styles from "../page.module.scss";

interface Props {
  value: TimeContext;
  onChange: (ctx: TimeContext) => void;
}

const rangeOptions: { value: TimeRange; label: string }[] = [
  { value: "total", label: "总计" },
  { value: "year", label: "年度" },
  { value: "month", label: "月度" },
];

const now = new Date();
const thisYear = now.getFullYear();
const thisMonth = now.getMonth() + 1;
const yearOptions = Array.from({ length: thisYear - 2025 + 1 }, (_, i) => 2026 + i);
const monthOptions = Array.from({ length: 12 }, (_, i) => i + 1);

export default function TimeRangeSelector({ value, onChange }: Props) {
  const showYear = value.range === "year" || value.range === "month";
  const showMonth = value.range === "month";

  return (
    <div className={styles.rangeSelector}>
      <div className={styles.rangeBtnGroup}>
        {rangeOptions.map((opt) => (
          <button
            key={opt.value}
            className={`${styles.rangeBtn} ${value.range === opt.value ? styles.rangeBtnActive : ""}`}
            onClick={() =>
              onChange({
                range: opt.value,
                year: thisYear,
                month: thisMonth,
              })
            }
          >
            {opt.label}
          </button>
        ))}
      </div>

      {showYear && (
        <div className={styles.rangePickers}>
          <Select
            size="small"
            value={value.year}
            onChange={(y) => onChange({ ...value, year: y })}
            style={{ width: 90 }}
            options={yearOptions.map((y) => ({ value: y, label: `${y}年` }))}
          />
          {showMonth && (
            <Select
              size="small"
              value={value.month}
              onChange={(m) => onChange({ ...value, month: m })}
              style={{ width: 80 }}
              options={monthOptions.map((m) => ({ value: m, label: `${m}月` }))}
            />
          )}
        </div>
      )}
    </div>
  );
}