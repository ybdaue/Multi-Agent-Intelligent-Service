"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { signin } from "@/lib/server/login";
import { checkBanned } from "@/lib/server/login/check-banned";
import { getSession } from "@/lib/auth-clients";
import ThemeToggle from "@/components/theme-toggle";
import styles from "./index.module.scss";

const LoginScene = dynamic(() => import("./login-scene"), { ssr: false });

const features = [
  {
    label: "智能对话",
    svg: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
      </svg>
    ),
  },
  {
    label: "数据分析",
    svg: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 20V10" /><path d="M12 20V4" /><path d="M6 20v-6" />
      </svg>
    ),
  },
  {
    label: "内容生成",
    svg: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5A2.5 2.5 0 016.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
        <path d="M8 7h6" /><path d="M8 11h8" />
      </svg>
    ),
  },
  {
    label: "财务管理",
    svg: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" /><path d="M16 8h-6a2 2 0 100 4h4a2 2 0 110 4H8" /><path d="M12 18V6" />
      </svg>
    ),
  },
];

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [reasonOverlay, setReasonOverlay] = useState<string | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  // 错误提示 2 秒后自动消失
  useEffect(() => {
    if (!error) return;
    const t = setTimeout(() => setError(""), 2000);
    return () => clearTimeout(t);
  }, [error]);

  /** 登录成功后完整页面跳转，刷新根 layout 的 Header session */
  function redirectAfterLogin() {
    window.location.href = "/home";
  }

  useEffect(() => {
    getSession().then(({ data }) => {
      if (data?.session) redirectAfterLogin();
    }).catch(() => {});
  }, []);

  // 从 URL 读取 reason 参数（被踢/封禁/过期），弹遮罩提示
  useEffect(() => {
    const reason = new URLSearchParams(window.location.search).get("reason")
    if (reason) {
      setReasonOverlay(decodeURIComponent(reason))
    }
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const { banned } = await checkBanned(email);
      if (banned) {
        setError("账号已被封禁，无法登录");
        setLoading(false);
        return;
      }

      const res = await signin({ email, password });
      if (!res.success) {
        setError(res.error);
        setLoading(false);
        return;
      }
      redirectAfterLogin();
    } catch {
      setError("操作失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className={styles.page}>
      <div className={styles.bgGradient} />
      <div className={styles.bgGrid} />
      <div className={styles.bgRing} />
      <div className={styles.bgShapes}>
        <div className={styles.shape1} />
        <div className={styles.shape2} />
        <div className={styles.shape3} />
        <div className={styles.shape4} />
      </div>
      <LoginScene anchorRef={cardRef} />
      <div className={styles.wrapper}>
        <div className={styles.card} ref={cardRef}>
          <ThemeToggle variant="icon" className={styles.themeTogglePosition} />
          <div className={styles.logoSection}>
            <div className={styles.logo}>
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a4 4 0 014 4c0 2-2 3-4 5-2-2-4-3-4-5a4 4 0 014-4z"/>
                <path d="M6 15c0-1.5 1.5-2 3-3 1.5 1 3 1.5 3 3 0 1.5-1.5 2-3 3-1.5-1-3-1.5-3-3z"/>
                <path d="M18 15c0-1.5-1.5-2-3-3-1.5 1-3 1.5-3 3 0 1.5 1.5 2 3 3 1.5-1 3-1.5 3-3z"/>
                <path d="M12 20v2"/>
                <path d="M8 22h8"/>
              </svg>
            </div>
            <h1 className={styles.title}>AI 智能平台</h1>
            <p className={styles.subtitle}>登录以访问您的智能助手</p>
          </div>

          <form onSubmit={handleSubmit} className={styles.form}>
            <div className={styles.field}>
              <div className={styles.inputWrapper}>
                <span className={styles.inputIcon}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="2" y="4" width="20" height="16" rx="2" />
                    <path d="m22 7-8.97 5.7a1.94 1.94 0 01-2.06 0L2 7" />
                  </svg>
                </span>
                <input
                  type="email" autoComplete="email" placeholder="name@example.com"
                  value={email} onChange={(e) => setEmail(e.target.value)} required
                  className={styles.input}
                />
              </div>
            </div>
            <div className={styles.field}>
              <div className={styles.inputWrapper}>
                <span className={styles.inputIcon}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0110 0v4" />
                  </svg>
                </span>
                <input
                  type="password" autoComplete="current-password" placeholder="请输入密码"
                  value={password} onChange={(e) => setPassword(e.target.value)} required
                  className={styles.input}
                />
              </div>
            </div>

            <div className={styles.forgot}>
              <span className={styles.forgotNote}>忘记密码？请联系管理员重置</span>
            </div>

            {error && <p key={error} className={styles.error}>{error}</p>}

            <button type="submit" disabled={loading} className={styles.button}>
              {loading ? (
                <span className={styles.loadingRing} />
              ) : (
                "登录"
              )}
            </button>
          </form>

          <div className={styles.signupHint}>
            还没有账号？请联系管理员开通
          </div>

          <div className={styles.features}>
            {features.map((f) => (
              <div key={f.label} className={styles.feature}>
                <span className={styles.featureIcon}>{f.svg}</span>
                {f.label}
              </div>
            ))}
          </div>

          <div className={styles.legal}>
            <Link href="/terms">服务条款</Link>
            <span className={styles.legalDot}>·</span>
            <Link href="/privacy">隐私政策</Link>
          </div>
        </div>
      </div>

          {/* 装饰粒子 */}
        <div className={styles.decorLeft}>
          <div className={styles.decorDot1} />
          <div className={styles.decorDot2} />
          <div className={styles.decorDot3} />
          <div className={styles.decorDot4} />
          <div className={styles.decorDot5} />
          <div className={styles.decorDot6} />
          <div className={styles.decorDot7} />
          <div className={styles.decorDot8} />
          <div className={styles.decorRing1} />
          <div className={styles.decorRing2} />
        </div>
        <div className={styles.decorTop}>
          <div className={styles.decorTopDot1} />
          <div className={styles.decorTopDot2} />
          <div className={styles.decorTopDot3} />
          <div className={styles.decorTopDot4} />
          <div className={styles.decorTopDot5} />
        </div>
        <div className={styles.exitOverlay} />
      </div>

      {reasonOverlay && (
        <div className={styles.reasonOverlay}>
          <div className={styles.reasonCard}>
            <div className={styles.reasonIcon}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <p className={styles.reasonTitle}>提示</p>
            <p className={styles.reasonText}>{reasonOverlay}</p>
            <button
              className={styles.reasonButton}
              onClick={() => {
                setReasonOverlay(null)
                window.history.replaceState(null, "", "/login")
              }}
            >确定</button>
          </div>
        </div>
      )}
    </>
  );
}