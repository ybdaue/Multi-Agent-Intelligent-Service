"use client";

import "@ant-design/v5-patch-for-react-19";

import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ConfigProvider, Layout, Menu, App, theme as antTheme } from "antd";
import {
  DashboardOutlined,
  UserOutlined,
  DollarOutlined,
  GiftOutlined,
  FileTextOutlined,
  OrderedListOutlined,
  BookOutlined,
  ShoppingCartOutlined,
  BellOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { useTheme } from "next-themes";
import zhCN from "antd/locale/zh_CN";
import AIChatPanel from "./_components/AIChatPanel";
import styles from "./layout.module.scss";

const { Sider, Content } = Layout;

export default function AdminLayoutClient({
  children, role,
}: {
  children: React.ReactNode; role: string;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const [aiPanelCollapsed, setAiPanelCollapsed] = useState(true);

  const selectedKey = "/" + pathname.split("/").slice(1).join("/");

  const menuItems = [
    { key: "/admin", icon: <DashboardOutlined />, label: "仪表盘" },
    { key: "/admin/users", icon: <UserOutlined />, label: "账号管理" },
    { key: "/admin/novels", icon: <BookOutlined />, label: "小说管理" },
    ...(role === "superAdmin" ? [{ key: "/admin/pricing", icon: <DollarOutlined />, label: "模型管理" }] : []),
    { key: "/admin/orders", icon: <ShoppingCartOutlined />, label: "订单管理" },
    { key: "/admin/plans", icon: <GiftOutlined />, label: "套餐管理" },
    { key: "/admin/recharge", icon: <DollarOutlined />, label: "余额管理" },
    { key: "/admin/billing", icon: <FileTextOutlined />, label: "消费账单" },
    { key: "/admin/user-plans", icon: <OrderedListOutlined />, label: "套餐账单" },
    { key: "/admin/announcements", icon: <BellOutlined />, label: "系统公告" },
    { key: "/admin/audit-logs", icon: <SafetyCertificateOutlined />, label: "操作日志" },
  ];

  return (
    <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm: isDark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
          token: isDark ? {
            colorBgContainer: "rgba(30, 41, 59, 0.8)",
            colorBgLayout: "#0f172a",
            colorBorder: "rgba(255, 255, 255, 0.08)",
            colorText: "#f1f5f9",
            colorTextSecondary: "rgba(255, 255, 255, 0.55)",
            colorPrimary: "#6366f1",
            colorPrimaryHover: "#818cf8",
            colorPrimaryBg: "rgba(99, 102, 241, 0.08)",
          } : {
            colorBgContainer: "#ffffff",
            colorBgLayout: "#f0f4f8",
            colorBorder: "#e5e7eb",
            colorText: "#111827",
            colorTextSecondary: "#6b7280",
            colorPrimary: "#6366f1",
            colorPrimaryHover: "#4f46e5",
          },
        }}
      >
        <Layout className={styles.layout}>
          <Sider className={styles.sider} width={200}>
            <Menu
              mode="inline"
              selectedKeys={[selectedKey]}
              items={menuItems}
              onClick={({ key }) => router.push(key)}
              style={{ borderRight: 0, background: "transparent" }}
            />
          </Sider>
          <div className={styles.contentWrap}>
            <Content className={styles.content}>
              <App>{children}</App>
            </Content>
          </div>
          <AIChatPanel collapsed={aiPanelCollapsed} onToggle={setAiPanelCollapsed} />
        </Layout>
      </ConfigProvider>
  );
}