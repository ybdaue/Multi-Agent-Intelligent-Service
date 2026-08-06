"use client";

import { useState, useCallback } from "react";
import styles from "../page.module.scss";

function AiSparkleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2v4m0 12v4m-8-12H2m20 0h-2m-3.5-6.5 2-2m-13 13-2 2m0-13 2 2m13 13-2-2" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function AiChartIcon() {
  return (
    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3v18h18" />
      <path d="M7 16l4-8 4 4 4-6" />
      <circle cx="18" cy="8" r="1" fill="currentColor" />
    </svg>
  );
}

interface AiAnalysisPanelProps {
  stockName: string;
  change: number;
  changePercent: number;
  price: number;
  symbol: string;
}

export default function AiAnalysisPanel({
  stockName, change, changePercent, price, symbol,
}: AiAnalysisPanelProps) {
  const [aiContent, setAiContent] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);

  const handleAiAnalysis = useCallback(async () => {
    setAiLoading(true);
    setAiContent(null);
    await new Promise((r) => setTimeout(r, 1200));
    setAiContent(
      `${stockName}（${symbol}）近期走势整体偏${change >= 0 ? "强" : "弱"}，` +
      `最新价 ${price.toFixed(2)} 元，今日${change >= 0 ? "上涨" : "下跌"} ` +
      `${Math.abs(changePercent).toFixed(2)}%。` +
      `建议关注后续成交量的变化以及市场整体情绪。此分析仅供参考，不构成投资建议。`
    );
    setAiLoading(false);
  }, [stockName, symbol, change, changePercent, price]);

  return (
    <div className={styles.aiSection}>
      <div className={styles.aiHeader}>
        <AiSparkleIcon />
        AI 分析
      </div>
      <div className={styles.aiBody}>
        {!aiContent && !aiLoading && (
          <div className={styles.aiEmpty}>
            <AiChartIcon />
            <p>点击下方按钮获取 AI 对 {stockName} 的行情分析</p>
            <button className={styles.aiBtn} onClick={handleAiAnalysis}>AI 分析</button>
          </div>
        )}
        {aiLoading && (
          <div className={styles.aiLoading}>
            <div className={styles.spinner} />
            <p>AI 分析中...</p>
          </div>
        )}
        {aiContent && !aiLoading && (
          <div className={styles.aiResult}>
            <p>{aiContent}</p>
            <button className={styles.aiBtn} onClick={handleAiAnalysis}>重新分析</button>
          </div>
        )}
      </div>
    </div>
  );
}
