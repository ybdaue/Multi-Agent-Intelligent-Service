"use client";

import styles from "./index.module.scss";

interface IntradayChartProps {
  ticks: { time: string; price: number }[];
  change: number;
  width?: number;
  height?: number;
}

export default function IntradayChart({
  ticks,
  change,
  width = 600,
  height = 220,
}: IntradayChartProps) {
  const prices = ticks.map((t) => t.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;
  const color = change >= 0 ? "#dc2626" : "#16a34a";

  const points = prices
    .map((v, i) => {
      const x = (i / (prices.length - 1)) * width;
      const y = height - ((v - min) / range) * (height - 20) - 10;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const areaPoints = `0,${height} ${points} ${width},${height}`;

  const gridLines = [0, 0.25, 0.5, 0.75, 1].map((t) => {
    const y = height - t * (height - 20) - 10;
    return { y, label: (min + range * t).toFixed(2) };
  });

  return (
    <svg
      className={styles.chartContainer}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
    >
      {gridLines.map((g, i) => (
        <g key={i}>
          <line
            x1="0"
            y1={g.y}
            x2={width}
            y2={g.y}
            stroke="var(--color-border)"
            strokeOpacity="0.5"
            strokeDasharray="4 4"
          />
          <text
            x={width - 5}
            y={g.y - 4}
            textAnchor="end"
            fill="var(--color-text-tertiary)"
            fontSize="11"
          >
            {g.label}
          </text>
        </g>
      ))}
      <polygon points={areaPoints} fill={color} fillOpacity="0.06" />
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle
        cx={points.split(" ").pop()!.split(",")[0]}
        cy={points.split(" ").pop()!.split(",")[1]}
        r="3"
        fill={color}
      />
    </svg>
  );
}
