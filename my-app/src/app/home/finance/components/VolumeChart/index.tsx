"use client";

import { useMemo } from "react";
import type { KlineResponseData } from "../types";
import styles from "./index.module.scss";

interface VolumeChartProps {
  data: KlineResponseData | null;
}

export default function VolumeChart({ data }: VolumeChartProps) {
  const bars = useMemo(() => {
    if (!data) return [];
    const maxVol = Math.max(...data.volume, 1);
    return data.timestamp.map((ts, i) => ({
      time: ts,
      ratio: data.volume[i] / maxVol,
      isUp: data.close[i] >= data.open[i],
    }));
  }, [data]);

  if (!data || !bars.length) {
    return <div className={styles.placeholder}>成交量 (暂无数据)</div>;
  }

  return (
    <svg className={styles.svg} viewBox={`0 0 ${bars.length} 100`} preserveAspectRatio="none">
      {bars.map((bar, i) => (
        <rect
          key={i}
          x={i}
          y={100 - bar.ratio * 85}
          width={0.8}
          height={Math.max(bar.ratio * 85, 0.5)}
          fill={bar.isUp ? "#dc2626" : "#16a34a"}
          fillOpacity="0.5"
          rx="0.3"
        />
      ))}
    </svg>
  );
}
