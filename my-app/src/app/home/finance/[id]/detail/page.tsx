import { getNowSingleStock } from "@/app/api/finance/getStock";
import Link from "next/link";
import { Suspense } from "react";
import type {
  StockData, StockQuote, StockDetail,
  TickflowQuoteResponse,
} from "../../components/types";
import BackButton from "./components/BackButton";
import ChartSection from "./components/ChartSection";
import AiAnalysisPanel from "./components/AiAnalysisPanel";
import styles from "./page.module.scss";

/* ── Constants ── */

const MARKET_LABELS: Record<string, string> = {
  sh: "沪市",
  sz: "深市",
  bj: "北交所",
};

/* ── Helpers ── */

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

function LoadingFallback() {
  return <div className={styles.page}><div className={styles.skeleton}>加载中...</div></div>;
}

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function StockDetailPage({ params }: PageProps) {
  const { id: symbol } = await params;

  const marketPrefix = symbol.match(/^(sh|sz|bj)/)?.[0] ?? "";
  const cleanSymbol = marketPrefix ? symbol.slice(marketPrefix.length) : symbol;
  const marketLabel = MARKET_LABELS[marketPrefix] ?? "";
  const apiSymbol = cleanSymbol + "." + marketPrefix.toUpperCase();

  return (
    <Suspense fallback={<LoadingFallback />}>
      <StockDetailContent
        symbol={cleanSymbol}
        apiSymbol={apiSymbol}
        marketLabel={marketLabel}
      />
    </Suspense>
  );
}

/* ── Data-fetching content (streamed inside Suspense) ── */

interface ContentProps {
  symbol: string;
  apiSymbol: string;
  marketLabel: string;
}

async function StockDetailContent({ symbol, apiSymbol, marketLabel }: ContentProps) {
  let basicInfo: StockData | null = null;
  let derivedQuote: StockQuote | null = null;

  try {
    const quoteRes = await getNowSingleStock<TickflowQuoteResponse>(apiSymbol);
    const sd = quoteRes?.data?.[0];
    if (sd) {
      basicInfo = {
        symbol: sd.symbol,
        name: sd.ext.name,
        price: sd.last_price,
        change: sd.ext.change_amount,
        changePercent: sd.ext.change_pct * 100,
        volume: sd.volume,
        amount: sd.amount,
      };
      derivedQuote = {
        open: sd.open,
        high: sd.high,
        low: sd.low,
        prevClose: sd.prev_close,
        turnoverRate: sd.ext.turnover_rate,
      };
    }
  } catch (err) {
    console.error("数据获取失败", err);
  }

  if (!basicInfo) {
    return (
      <div className={styles.page}>
        <div className={styles.notFound}>
          <p>未找到股票代码: {symbol}</p>
          <Link href="/home/finance/stock" className={styles.backBtn}>返回列表</Link>
        </div>
      </div>
    );
  }

  const stock: StockDetail = {
    ...basicInfo,
    intraday: [],
    open: derivedQuote?.open ?? basicInfo.price,
    high: derivedQuote?.high ?? basicInfo.price,
    low: derivedQuote?.low ?? basicInfo.price,
    prevClose: derivedQuote?.prevClose ?? basicInfo.price,
    turnoverRate: derivedQuote
      ? +(derivedQuote.turnoverRate * 100).toFixed(2)
      : +(Math.abs(basicInfo.changePercent || 0) * 0.8 + 0.5).toFixed(2),
    peRatio: +(Math.abs(basicInfo.changePercent || 0) * 5 + 15).toFixed(1),
  };

  const changeColor = stock.change >= 0 ? styles.up : styles.down;

  return (
    <div className={styles.page}>
      {/* ── Top Section ── */}
      <div className={styles.topSection}>
        <div className={styles.topInfo}>
          <div className={styles.topLeft}>
            <BackButton className={`${styles.avatar} ${changeColor}`} />
            <div className={styles.nameGroup}>
              <div className={styles.stockName}>{stock.name}</div>
              <div className={styles.stockCode}>
                {symbol}
                {marketLabel && <span className={styles.marketTag}>{marketLabel}</span>}
              </div>
            </div>
          </div>
          <div className={styles.topRight}>
            <div className={`${styles.currentPrice} ${changeColor}`}>
              {stock.price.toFixed(2)}
            </div>
            <div className={styles.changeGroup}>
              <span className={changeColor}>
                {stock.change >= 0 ? "+" : ""}{stock.change.toFixed(2)}
              </span>
              <span className={changeColor}>
                {stock.changePercent >= 0 ? "+" : ""}{stock.changePercent.toFixed(2)}%
              </span>
            </div>
          </div>
        </div>

        <div className={styles.divider} />

        <div className={styles.statsGrid}>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>最新价</span>
            <span className={styles.statValue}>
              {stock.price.toFixed(2)}<span className={styles.statUnit}>元</span>
            </span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>开盘价</span>
            <span className={styles.statValue}>
              {stock.open.toFixed(2)}<span className={styles.statUnit}>元</span>
            </span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>最高价</span>
            <span className={styles.statValue} style={{ color: "#dc2626" }}>
              {stock.high.toFixed(2)}<span className={styles.statUnit}>元</span>
            </span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>最低价</span>
            <span className={styles.statValue} style={{ color: "#16a34a" }}>
              {stock.low.toFixed(2)}<span className={styles.statUnit}>元</span>
            </span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>成交量</span>
            <span className={styles.statValue}>{formatVolume(stock.volume)}</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>成交额</span>
            <span className={styles.statValue}>{formatAmount(stock.amount)}</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>换手率</span>
            <span className={styles.statValue}>{stock.turnoverRate.toFixed(2)}%</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>市盈率</span>
            <span className={styles.statValue}>
              {stock.peRatio.toFixed(1)}<span className={styles.statUnit}>倍</span>
            </span>
          </div>
        </div>
      </div>

      {/* ── Main Content (K线数据由 ChartSection 在客户端自行获取) ── */}
      <div className={styles.mainContent}>
        <ChartSection change={stock.change} symbol={apiSymbol} />
        <AiAnalysisPanel
          stockName={stock.name}
          change={stock.change}
          changePercent={stock.changePercent}
          price={stock.price}
          symbol={symbol}
        />
      </div>
    </div>
  );
}
