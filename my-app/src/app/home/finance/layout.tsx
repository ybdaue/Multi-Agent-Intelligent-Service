"use client";

import { Suspense } from "react";
import {
  LineChartOutlined,
  StarOutlined,
  WalletOutlined,
  BulbOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import SideBarLeft, { type SideBarItem } from "@/app/home/components/SideBarLeft";
import styles from "./layout.module.scss";

const menuItems: SideBarItem[] = [
  { label: "股票分析", icon: <LineChartOutlined />, path: "/home/finance/stock" },
  { label: "我的自选", icon: <StarOutlined />, path: "/home/finance/favorites" },
  { label: "我的持仓", icon: <WalletOutlined />, path: "/home/finance/portfolio" },
  { label: "投资策略", icon: <BulbOutlined />, path: "/home/finance/strategy" },
  { label: "AI助手", icon: <RobotOutlined />, path: "/home/finance/content" },
];

export default function FinanceLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.layout}>
      <Suspense fallback={null}>
        <SideBarLeft menuItems={menuItems} title="金融智能服务" />
      </Suspense>
      <Suspense fallback={<div>Loading...</div>}>
        {children}
      </Suspense>
    </div>
  );
}
