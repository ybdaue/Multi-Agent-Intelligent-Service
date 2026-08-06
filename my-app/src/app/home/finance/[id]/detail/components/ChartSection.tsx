"use client";

import { useState } from "react";
import type { SubChart } from "../../../components/types";
import IntradayChart from "../../../components/IntradayChart";
import KlineChart from "../../../components/KlineChart";
import SubChartPanel from "../../../components/SubChartPanel";
import styles from "../page.module.scss";

interface ChartSectionProps {
  change: number;
  symbol: string;
}

export default function ChartSection({ change, symbol }: ChartSectionProps) {
  const [leftSubCharts, setLeftSubCharts] = useState<SubChart[]>([{ id: "1", type: "volume" }]);
  const [rightSubCharts, setRightSubCharts] = useState<SubChart[]>([{ id: "1", type: "volume" }]);

  return (
    <div className={styles.chartSection}>
      <div className={styles.chartColumns}>
        <div className={styles.chartColumn}>
          <div className={styles.mainChart}>
            <span className={styles.chartLabel}>分时图</span>
            <IntradayChart ticks={[]} change={change} />
          </div>
          <SubChartPanel subCharts={leftSubCharts} setSubCharts={setLeftSubCharts} />
        </div>

        <div className={styles.chartColumn}>
          <div className={styles.mainChart}>
            <KlineChart symbol={symbol} />
          </div>
          <SubChartPanel subCharts={rightSubCharts} setSubCharts={setRightSubCharts} />
        </div>
      </div>
    </div>
  );
}
