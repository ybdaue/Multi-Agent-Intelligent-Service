"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import styles from "./index.module.scss";

interface Props {
  variant: "icon" | "switch";
  className?: string;
}

export default function ThemeToggle({ variant, className }: Props) {
  const [mounted, setMounted] = useState(false);
  const { theme, setTheme } = useTheme();

  useEffect(() => { setMounted(true); }, []);

  if (!mounted) return null;

  const isDark = theme === "dark";
  const toggle = () => setTheme(isDark ? "light" : "dark");

  const cls = [variant === "icon" ? styles.iconToggle : styles.switchToggle, className]
    .filter(Boolean)
    .join(" ");

  if (variant === "icon") {
    return (
      <button onClick={toggle} className={cls} aria-label="切换主题">
        {isDark ? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2" /><path d="M12 20v2" />
            <path d="m4.93 4.93 1.41 1.41" /><path d="m17.66 17.66 1.41 1.41" />
            <path d="M2 12h2" /><path d="M20 12h2" />
            <path d="m6.34 17.66-1.41 1.41" /><path d="m19.07 4.93-1.41 1.41" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        )}
      </button>
    );
  }

  return (
    <button onClick={toggle} className={cls} aria-label="切换主题">
      <span className={`${styles.switchKnob}${isDark ? ` ${styles.dark}` : ""}`} />
    </button>
  );
}