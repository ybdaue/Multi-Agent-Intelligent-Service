"use client";

import { useState } from "react";
import { signOut } from "@/lib/auth-clients";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import ThemeToggle from "@/components/theme-toggle";
import styles from "./index.module.scss";

interface Props {
  userName?: string | null;
  userEmail?: string | null;
}

export default function SettingsMenu({ userName, userEmail }: Props) {
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);
  const { theme } = useTheme();

  async function handleLogout() {
    setLoggingOut(true);
    await signOut();
    router.replace("/login");
  }

  return (
    <div className={styles.menu}>
      <div className={styles.userInfo}>
        <p className={styles.userName}>{userName ?? "用户"}</p>
        <p className={styles.userEmail}>{userEmail}</p>
      </div>

      <div className={styles.themeRow}>
        <span className={styles.themeLabel}>
          {theme === "dark" ? "深色模式" : "浅色模式"}
        </span>
        <ThemeToggle variant="switch" />
      </div>

      <div className={styles.divider}>
        <button
          onClick={handleLogout}
          disabled={loggingOut}
          className={`${styles.menuItem} ${styles.danger}`}
        >
          {loggingOut ? "退出中..." : "退出登录"}
        </button>
      </div>
    </div>
  );
}
