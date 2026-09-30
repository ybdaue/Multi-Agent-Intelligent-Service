"use client";

import "@ant-design/v5-patch-for-react-19";

import { useState } from "react";
import { Typography } from "antd";
import TimeRangeSelector from "./_components/TimeRangeSelector";
import StatCards from "./_components/StatCards";
import ChartSection from "./_components/ChartSection";
import ModelRankingTable from "./_components/ModelRankingTable";
import UserTopTable from "./_components/UserTopTable";
import PlanRankingTable from "./_components/PlanRankingTable";
import ServiceRankingTable from "./_components/ServiceRankingTable";
import type { TimeContext } from "./types/dashboard";
import styles from "./page.module.scss";

const now = new Date();

export default function AdminDashboard() {
  const [timeContext, setTimeContext] = useState<TimeContext>({
    range: "total",
    year: now.getFullYear(),
    month: now.getMonth() + 1,
  });

  return (
    <div className={styles.dashboard}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          运营仪表盘
        </Typography.Title>
      </div>

      <TimeRangeSelector value={timeContext} onChange={setTimeContext} />

      <StatCards timeContext={timeContext} />

      {timeContext.range !== "total" && <ChartSection timeContext={timeContext} />}

      <div className={styles.tableGrid}>
        <ModelRankingTable timeContext={timeContext} />
        <UserTopTable timeContext={timeContext} />
      </div>

      <div className={styles.tableGrid}>
        <PlanRankingTable timeContext={timeContext} />
        <ServiceRankingTable timeContext={timeContext} />
      </div>
    </div>
  );
}