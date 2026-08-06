"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from "@ant-design/icons";
import styles from "./index.module.scss";

export interface SideBarItem {
  label: string;
  icon: React.ReactNode;
  path: string;
}

interface SideBarLeftProps {
  menuItems: SideBarItem[];
  title: string;
  logoIcon?: React.ReactNode;
}

export default function SideBarLeft({ menuItems, title, logoIcon }: SideBarLeftProps) {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();

  return (
    <aside className={`${styles.sidebar} ${collapsed ? styles.collapsed : ""}`}>
      <div className={styles.header}>
        {collapsed ? (
          <span className={styles.logoIcon}>{logoIcon}</span>
        ) : (
          <span className={styles.title}>{title}</span>
        )}
        <button
          className={styles.toggleBtn}
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? "展开侧栏" : "收起侧栏"}
        >
          {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        </button>
      </div>

      <nav className={styles.menu}>
        {menuItems.map((item) => {
          const isActive = pathname === item.path || pathname.startsWith(item.path + "/");
          return (
            <Link
              key={item.path}
              href={item.path}
              className={`${styles.menuItem} ${isActive ? styles.active : ""}`}
              title={collapsed ? item.label : undefined}
            >
              <span className={styles.icon}>{item.icon}</span>
              {!collapsed && <span className={styles.label}>{item.label}</span>}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
