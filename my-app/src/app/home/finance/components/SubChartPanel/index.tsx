"use client";

import type { SubChart } from "../types";
import styles from "./index.module.scss";

const SUB_CHART_OPTIONS = [
  { value: "volume", label: "成交量" },
  { value: "macd", label: "MACD" },
  { value: "kdj", label: "KDJ" },
  { value: "rsi", label: "RSI" },
  { value: "boll", label: "BOLL" },
];

function SubChartPlaceholder({ type }: { type: string }) {
  const labels: Record<string, string> = {
    volume: "成交量",
    macd: "MACD",
    kdj: "KDJ",
    rsi: "RSI",
    boll: "BOLL",
  };

  return (
    <svg
      width="100%"
      height="100%"
      viewBox="0 0 500 100"
      preserveAspectRatio="none"
      style={{ display: "block" }}
    >
      <text
        x="50%"
        y="50%"
        textAnchor="middle"
        dominantBaseline="central"
        fill="var(--color-text-tertiary)"
        fontSize="13"
      >
        {labels[type] || type}
      </text>
      {type === "volume" && (
        <>
          {[30, 40, 50, 60, 70, 45, 55, 65, 35, 50, 60, 40, 55, 45, 65, 50, 40, 60, 55, 45].map(
            (h, i) => {
              const barW = 500 / 20 - 4;
              const barH = (h / 80) * 80;
              return (
                <rect
                  key={i}
                  x={i * (500 / 20) + 2}
                  y={90 - barH}
                  width={barW}
                  height={barH}
                  fill="#6366f1"
                  fillOpacity="0.5"
                  rx="2"
                />
              );
            },
          )}
        </>
      )}
    </svg>
  );
}

interface SubChartPanelProps {
  subCharts: SubChart[];
  setSubCharts: React.Dispatch<React.SetStateAction<SubChart[]>>;
}

export default function SubChartPanel({ subCharts, setSubCharts }: SubChartPanelProps) {
  const addSubChart = () => {
    if (subCharts.length >= 3) return;
    const used = subCharts.map((c) => c.type);
    const next = SUB_CHART_OPTIONS.find((o) => !used.includes(o.value));
    if (next) setSubCharts((prev) => [...prev, { id: String(Date.now()), type: next.value }]);
  };

  const removeSubChart = (id: string) => {
    setSubCharts((prev) => prev.filter((c) => c.id !== id));
  };

  const updateSubChartType = (id: string, type: string) => {
    setSubCharts((prev) => prev.map((c) => (c.id === id ? { ...c, type } : c)));
  };

  const availableOptions = SUB_CHART_OPTIONS.filter(
    (o) => !subCharts.find((c) => c.type === o.value),
  );

  return (
    <div className={styles.subCharts}>
      {subCharts.map((sc) => (
        <div key={sc.id} className={styles.subChart}>
          <div className={styles.subChartHeader}>
            <select value={sc.type} onChange={(e) => updateSubChartType(sc.id, e.target.value)}>
              {SUB_CHART_OPTIONS.map((o) => (
                <option
                  key={o.value}
                  value={o.value}
                  disabled={
                    o.value !== sc.type && subCharts.some((c) => c.id !== sc.id && c.type === o.value)
                  }
                >
                  {o.label}
                </option>
              ))}
            </select>
            <button className={styles.subChartClose} onClick={() => removeSubChart(sc.id)}>
              ×
            </button>
          </div>
          <div className={styles.subChartBody}>
            <SubChartPlaceholder type={sc.type} />
          </div>
        </div>
      ))}
      {subCharts.length < 3 && availableOptions.length > 0 && (
        <button className={styles.addChartBtn} onClick={addSubChart}>
          + 添加图表
        </button>
      )}
    </div>
  );
}
