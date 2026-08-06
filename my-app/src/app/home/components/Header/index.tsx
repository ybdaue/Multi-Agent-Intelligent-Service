"use client";

import { useState, useRef, useEffect } from "react";
import Image from "next/image";
import SettingsMenu from "../SettingsMenu";
import styles from "./index.module.scss";

interface Props {
  userName?: string | null;
  userEmail?: string | null;
}

export default function Header({ userName, userEmail }: Props) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setSettingsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <header className={styles.header}>
      <div className={styles.logoSection}>
        <Image src="/logo.png" alt="Logo" width={36} height={36} className={styles.logo} />
        <span className={styles.brandName}>AI 智能平台</span>
      </div>

      <div className={styles.actions}>
        <div className={styles.menuWrapper} ref={menuRef}>
          <button
            onClick={() => setSettingsOpen(!settingsOpen)}
            className={styles.userBtn}
          >
            <span className={styles.userName}>{userName ?? "用户"}</span>
            <svg className={styles.icon} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>

          {settingsOpen && (
            <SettingsMenu userName={userName} userEmail={userEmail} />
          )}
        </div>
      </div>
    </header>
  );
}
