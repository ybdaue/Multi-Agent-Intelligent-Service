"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { debounce } from "@/lib/utils/debounce";
import { getStockList } from "@/app/api/finance/getStockList";
import styles from "../page.module.scss";

interface StockData {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  amount: number;
}

type SortKey = "price" | "change" | "changePercent" | "volume" | "amount";

interface SortConfig {
  key: SortKey;
  dir: "asc" | "desc";
}



const PAGE_SIZES = [10, 20, 30, 50];

const SORTABLE_COLUMNS: { key: SortKey; label: string }[] = [
  { key: "price", label: "最新价" },
  { key: "change", label: "涨跌额" },
  { key: "changePercent", label: "涨跌幅" },
  { key: "volume", label: "成交量" },
  { key: "amount", label: "成交额" },
];

function formatVolume(v: number): string {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
  if (v >= 1e4) return (v / 1e4).toFixed(2) + "万";
  return v.toFixed(0);
}

function formatAmount(v: number): string {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
  if (v >= 1e4) return (v / 1e4).toFixed(2) + "万";
  return v.toFixed(0);
}

function generateMiniTrend(symbol: string, change: number): number[] {
  const seed = parseInt(symbol, 10) || 0;
  const data: number[] = [];
  for (let i = 0; i < 20; i++) {
    const t = i / 19;
    const noise = Math.sin(seed + i * 7) * 0.5 * Math.max(Math.abs(change || 0.5), 0.1) * 0.3;
    const trend = change * t * 2;
    data.push(+(100 + trend + noise).toFixed(2));
  }
  return data;
}

function MiniChart({ symbol, change }: { symbol: string; change: number }) {
  const data = useMemo(() => generateMiniTrend(symbol, change), [symbol, change]);
  const width = 108;
  const height = 32;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const color = change >= 0 ? "#dc2626" : "#16a34a";

  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * width;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const areaPoints = `0,${height} ${points} ${width},${height}`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={styles.miniChart}
    >
      <polygon points={areaPoints} fill={color} fillOpacity="0.08" />
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle
        cx={points.split(" ").pop()!.split(",")[0]}
        cy={points.split(" ").pop()!.split(",")[1]}
        r="2"
        fill={color}
      />
    </svg>
  );
}

function SortIcon({
  columnKey,
  sort,
}: {
  columnKey: SortKey;
  sort: SortConfig | null;
}) {
  const isActive = sort?.key === columnKey;
  const dir = isActive ? sort!.dir : null;

  return (
    <span className={`${styles.sortIcon} ${isActive ? styles.active : ""}`}>
      <span style={{ display: dir === "asc" || !dir ? "block" : "none" }}>▲</span>
      <span style={{ display: dir === "desc" || !dir ? "block" : "none" }}>▼</span>
    </span>
  );
}

function TableSkeleton() {
  return (
    <table className={styles.stockTable}>
      <thead>
        <tr>
          {Array.from({ length: 8 }).map((_, i) => (
            <th key={i}><div className={styles.skeletonTh} /></th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: 8 }).map((_, i) => (
          <tr key={i}>
            {Array.from({ length: 8 }).map((_, j) => (
              <td key={j}><div className={styles.skeletonTd} /></td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}


export default function StockView() {
  const router = useRouter();

  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [sort, setSort] = useState<SortConfig | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const [stocks, setStocks] = useState<StockData[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const debouncedSearch = useMemo(
    () =>
      debounce((value: string) => {
        setKeyword(value);
        setPage(1);
      }, 500),
    [],
  );

  const handleKeywordChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setKeywordInput(e.target.value);
      debouncedSearch(e.target.value);
    },
    [debouncedSearch],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getStockList({
      page,
      pageSize,
      keyword: keyword || undefined,
      sortBy: sort?.key,
      sortDir: sort?.dir,
    })
      .then((res) => {
        if (cancelled) return;
        setStocks(res.stocks ?? []);
        setTotal(res.total ?? 0);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || "获取数据失败");
        setStocks([]);
        setTotal(0);
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [page, pageSize, keyword, sort]);

  const totalPages = Math.ceil(total / pageSize);

  const handleSort = (key: SortKey) => {
    setSort((prev) => {
      if (!prev || prev.key !== key) return { key, dir: "asc" };
      if (prev.dir === "asc") return { key, dir: "desc" };
      return null;
    });
  };

  const handleTableClick = (e: React.MouseEvent<HTMLTableSectionElement>) => {
    const tr = (e.target as HTMLElement).closest("tr");
    if (!tr || !tr.dataset.symbol) return;
    router.push(`/home/finance/${tr.dataset.symbol}/detail`);
  };

  return (
    <div className={styles.stockView}>
      <div className={styles.filterBar}>
        <input
          placeholder="搜索股票代码或名称"
          value={keywordInput}
          onChange={handleKeywordChange}
          style={{ minWidth: 220 }}
        />
        <span className={styles.filterCount}>
          {loading ? "加载中..." : `${total} 只股票`}
        </span>
      </div>

      <div className={styles.scrollArea}>
        {error ? (
          <table className={styles.stockTable}>
            <tbody>
              <tr>
                <td colSpan={8} style={{ textAlign: "center", padding: "3rem 1rem", color: "var(--color-text-tertiary)" }}>
                  {error}
                </td>
              </tr>
            </tbody>
          </table>
        ) : loading ? (
          <TableSkeleton />
        ) : (
          <table className={styles.stockTable}>
            <thead>
              <tr>
                <th style={{ width: 100 }} className={styles.cellFirst}>代码</th>
                <th style={{ width: 100 }}>名称</th>
                {SORTABLE_COLUMNS.map((col) => (
                  <th key={col.key} className={styles.colRight}>
                    <span
                      className={styles.sortHeader}
                      onClick={() => handleSort(col.key)}
                    >
                      {col.label}
                      <SortIcon columnKey={col.key} sort={sort} />
                    </span>
                  </th>
                ))}
                <th className={styles.colCenter} style={{ width: 130 }}>分时图</th>
              </tr>
            </thead>
            <tbody onClick={handleTableClick}>
              {stocks.length === 0 ? (
                <tr className={styles.emptyRow}>
                  <td colSpan={8}>暂无匹配数据</td>
                </tr>
              ) : (
                stocks.map((s) => (
                  <tr
                    key={s.symbol}
                    data-symbol={s.symbol}
                    className={styles.clickableRow}
                  >
                    <td className={styles.cellFirst}>
                      <span className={styles.symbol}>{s.symbol}</span>
                    </td>
                    <td><span className={styles.name}>{s.name}</span></td>
                    <td className={styles.price}>{s.price.toFixed(2)}</td>
                    <td
                      className={`${styles.change} ${s.change >= 0 ? styles.up : styles.down}`}
                    >
                      {s.change >= 0 ? "+" : ""}{s.change.toFixed(2)}
                    </td>
                    <td
                      className={`${styles.change} ${s.changePercent >= 0 ? styles.up : styles.down}`}
                    >
                      {s.changePercent >= 0 ? "+" : ""}{s.changePercent.toFixed(2)}%
                    </td>
                    <td className={styles.volume}>{formatVolume(s.volume)}</td>
                    <td className={styles.amount}>{formatAmount(s.amount)}</td>
                    <td className={styles.chartCell}>
                      <MiniChart symbol={s.symbol} change={s.change} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}
      </div>

      {!error && !loading && (
        <div className={styles.pagination}>
          <div className={styles.pageSizeControl}>
            每页
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
            >
              {PAGE_SIZES.map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
            条
          </div>

          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button>
          <span>
            第 {page} / {totalPages || 1} 页 (共 {total} 条)
          </span>
          <button disabled={page >= totalPages} onClick={() => setPage(page + 1)}>下一页</button>
        </div>
      )}
    </div>
  );
}
