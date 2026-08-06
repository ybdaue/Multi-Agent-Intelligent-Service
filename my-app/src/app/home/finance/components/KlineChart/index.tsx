"use client";

import { useMemo, useRef, useState, useCallback, useEffect } from "react";
import { createChart, ColorType, CandlestickSeries, LineSeries } from "lightweight-charts";
import { getSingleStockKline } from "@/app/api/finance/getStock";
import type { KlineResponseData, KlineResponse } from "../types";
import styles from "./index.module.scss";

/* ── Helpers ── */

function msToDateStr(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function getMonday(date: Date): Date {
  const d = new Date(date);
  const day = d.getDay();
  d.setDate(d.getDate() - day + (day === 0 ? -6 : 1));
  d.setHours(0, 0, 0, 0);
  return d;
}

function aggregateToWeekly(data: KlineResponseData): KlineResponseData {
  const weeks = new Map<string, { open: number; high: number; low: number; close: number }>();
  for (let i = 0; i < data.timestamp.length; i++) {
    const monday = getMonday(new Date(data.timestamp[i]));
    const key = msToDateStr(monday.getTime());
    if (!weeks.has(key)) {
      weeks.set(key, { open: data.open[i], high: data.high[i], low: data.low[i], close: data.close[i] });
    } else {
      const w = weeks.get(key)!;
      w.high = Math.max(w.high, data.high[i]);
      w.low = Math.min(w.low, data.low[i]);
      w.close = data.close[i];
    }
  }
  const sorted = Array.from(weeks.entries()).sort(([a], [b]) => a.localeCompare(b));
  return {
    timestamp: sorted.map(([key]) => new Date(key + "T00:00:00").getTime()),
    open: sorted.map(([, v]) => v.open),
    high: sorted.map(([, v]) => v.high),
    low: sorted.map(([, v]) => v.low),
    close: sorted.map(([, v]) => v.close),
    volume: [],
    amount: [],
  };
}

/* ── Component ── */

interface KlineChartProps {
  symbol: string;
}

export default function KlineChart({ symbol }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
  const seriesRef = useRef<ReturnType<ReturnType<typeof createChart>["addSeries"]> | null>(null);
  const bandUpperRef = useRef<any>(null);
  const bandMiddleRef = useRef<any>(null);
  const bandLowerRef = useRef<any>(null);

  const [type, setType] = useState<"daily" | "weekly">("daily");
  const [klineData, setKlineData] = useState<KlineResponseData | null>(null);
  const [klineLoading, setKlineLoading] = useState(true);
  const [visibleCount, setVisibleCount] = useState(100);
  const [offset, setOffset] = useState(0);

  // ── Fetch kline data ──
  useEffect(() => {
    let cancelled = false;
    setKlineLoading(true);
    getSingleStockKline<KlineResponse>(symbol, BigInt(10000))
      .then((res) => { if (!cancelled) setKlineData(res.data); })
      .catch(() => { if (!cancelled) setKlineData(null); })
      .finally(() => { if (!cancelled) setKlineLoading(false); });
    return () => { cancelled = true; };
  }, [symbol]);

  // ── Transform data ──
  const allPoints = useMemo(() => {
    if (!klineData) return [];
    const r = type === "daily" ? klineData : aggregateToWeekly(klineData);
    return r.timestamp.map((ts, i) => ({
      time: msToDateStr(ts),
      open: r.open[i],
      high: r.high[i],
      low: r.low[i],
      close: r.close[i],
    }));
  }, [klineData, type]);

  const maxOffset = Math.max(0, allPoints.length - visibleCount);

  useEffect(() => {
    setOffset((o) => Math.min(o, maxOffset));
  }, [maxOffset]);

  const candlestickData = useMemo(() => {
    if (!allPoints.length) return [];
    const end = allPoints.length - offset;
    const start = Math.max(0, end - visibleCount);
    return allPoints.slice(start, end);
  }, [allPoints, visibleCount, offset]);

  // ── Bollinger Bands (20-period, 2σ) ──
  const bollingerData = useMemo(() => {
    const period = 20;
    if (!allPoints.length) return { upper: [] as { time: string; value: number }[], middle: [], lower: [] };

    const closes = allPoints.map((p) => p.close);
    const upper: { time: string; value: number }[] = [];
    const middle: { time: string; value: number }[] = [];
    const lower: { time: string; value: number }[] = [];

    for (let i = 0; i < closes.length; i++) {
      const lookback = Math.min(i + 1, period);
      let sum = 0;
      for (let j = i - lookback + 1; j <= i; j++) sum += closes[j];
      const sma = sum / lookback;

      let sqSum = 0;
      for (let j = i - lookback + 1; j <= i; j++) sqSum += (closes[j] - sma) ** 2;
      const stddev = Math.sqrt(sqSum / lookback);

      const time = allPoints[i].time;
      middle.push({ time, value: sma });
      upper.push({ time, value: sma + 2 * stddev });
      lower.push({ time, value: sma - 2 * stddev });
    }

    return { upper, middle, lower };
  }, [allPoints]);

  const visibleBollinger = useMemo(() => {
    const end = allPoints.length - offset;
    const start = Math.max(0, end - visibleCount);
    return {
      upper: bollingerData.upper.slice(start, end),
      middle: bollingerData.middle.slice(start, end),
      lower: bollingerData.lower.slice(start, end),
    };
  }, [bollingerData, offset, visibleCount, allPoints.length]);

  // ── Create chart once on mount ──
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "transparent",
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "rgba(42,46,57,0.5)" },
        horzLines: { color: "rgba(42,46,57,0.5)" },
      },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      timeScale: {
        visible: false,
      },
      rightPriceScale: {
        visible: false,
      },
      crosshair: {
        vertLine: {
          color: "rgba(255,255,255,0.2)",
          style: 2,
          width: 1,
          labelVisible: false,
        },
        horzLine: {
          color: "rgba(255,255,255,0.2)",
          style: 2,
          width: 1,
          labelVisible: false,
        },
      },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#dc2626",
      downColor: "#16a34a",
      borderUpColor: "#dc2626",
      borderDownColor: "#16a34a",
      wickUpColor: "#dc2626",
      wickDownColor: "#16a34a",
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });

    chartRef.current = chart;
    seriesRef.current = series;

    // ── Bollinger Bands series ──
    const bandOpts = {
      lineWidth: 1 as const,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      priceFormat: { type: "price" as const, precision: 2, minMove: 0.01 },
    };
    bandUpperRef.current = chart.addSeries(LineSeries, { ...bandOpts, color: "#dc2626" });
    bandMiddleRef.current = chart.addSeries(LineSeries, { ...bandOpts, color: "#eab308" });
    bandLowerRef.current = chart.addSeries(LineSeries, { ...bandOpts, color: "#3b82f6" });

    // ── Tooltip ──
    const tooltip = document.createElement("div");
    tooltip.className = styles.tooltip;
    containerRef.current.appendChild(tooltip);

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.point || !tooltip) {
        tooltip.style.display = "none";
        return;
      }
      const pointData = param.seriesData.get(series) as any;
      if (!pointData) {
        tooltip.style.display = "none";
        return;
      }

      const isUp = pointData.close >= pointData.open;
      tooltip.className = `${styles.tooltip} ${isUp ? styles.tooltipUp : styles.tooltipDown}`;
      tooltip.innerHTML = `
        <div class="${styles.tooltipDate}">${pointData.time}</div>
        <div class="${styles.tooltipRow}">开: <span class="${styles.tooltipVal}">${pointData.open.toFixed(2)}</span></div>
        <div class="${styles.tooltipRow}">高: <span class="${styles.tooltipVal}">${pointData.high.toFixed(2)}</span></div>
        <div class="${styles.tooltipRow}">低: <span class="${styles.tooltipVal}">${pointData.low.toFixed(2)}</span></div>
        <div class="${styles.tooltipRow}">收: <span class="${styles.tooltipVal}">${pointData.close.toFixed(2)}</span></div>
      `;
      tooltip.style.display = "block";

      const rect = containerRef.current!.getBoundingClientRect();
      let left = param.point.x + 12;
      let top = param.point.y - 10;
      if (left + 130 > rect.width) left = param.point.x - 140;
      if (top < 4) top = 4;
      if (top + 120 > rect.height) top = rect.height - 124;
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
    });

    // ── Resize ──
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width: w, height: h } = entry.contentRect;
        if (w > 0 && h > 0) {
          chart.applyOptions({ width: w, height: h });
        }
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart.remove();
      tooltip.remove();
      chartRef.current = null;
      seriesRef.current = null;
      bandUpperRef.current = null;
      bandMiddleRef.current = null;
      bandLowerRef.current = null;
    };
  }, []);

  // ── Update data in-place when candlestickData changes ──
  useEffect(() => {
    if (!seriesRef.current || !candlestickData.length) return;
    seriesRef.current.setData(candlestickData);

    if (visibleBollinger.upper.length) {
      bandUpperRef.current?.setData(visibleBollinger.upper);
      bandMiddleRef.current?.setData(visibleBollinger.middle);
      bandLowerRef.current?.setData(visibleBollinger.lower);
    }

    chartRef.current?.timeScale().fitContent();
  }, [candlestickData, visibleBollinger]);

  // ── Count / offset handlers ──
  const handleDec = useCallback(() => setVisibleCount((c) => Math.max(50, c - 25)), []);
  const handleInc = useCallback(() => setVisibleCount((c) => Math.min(300, c + 25)), []);
  const handlePrev = useCallback(() => setOffset((o) => Math.min(o + 10, maxOffset)), [maxOffset]);
  const handleNext = useCallback(() => setOffset((o) => Math.max(o - 10, 0)), []);

  const typeLabel = type === "daily" ? "日K线" : "周K线";

  return (
    <div className={styles.wrapper}>
      <select
        className={styles.typeSelect}
        value={type}
        onChange={(e) => setType(e.target.value as "daily" | "weekly")}
      >
        <option value="daily">日K线</option>
        <option value="weekly">周K线</option>
      </select>

      <div ref={containerRef} className={styles.chartArea} />

      {(klineLoading || !candlestickData.length) && (
        <div className={styles.placeholder}>
          {klineLoading ? `${typeLabel} 加载中...` : `${typeLabel} (暂无数据)`}
        </div>
      )}

      {!klineLoading && candlestickData.length > 0 && (
        <div className={styles.controls}>
          <button className={`${styles.ctrlBtn} ${styles.shiftBtn}`} onClick={handlePrev} disabled={offset >= maxOffset} title="向前10条">‹</button>
          <button className={`${styles.ctrlBtn} ${styles.shiftBtn}`} onClick={handleNext} disabled={offset <= 0} title="向后10条">›</button>
          <span className={styles.countLabel}>{visibleCount}</span>
          <button className={styles.ctrlBtn} onClick={handleDec} disabled={visibleCount <= 50} title="减少25条">−</button>
          <button className={styles.ctrlBtn} onClick={handleInc} disabled={visibleCount >= 300} title="增加25条">+</button>
        </div>
      )}
    </div>
  );
}
