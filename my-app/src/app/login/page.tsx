"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { signin } from "@/lib/server/login";
import { getSession } from "@/lib/auth-clients";
import styles from "./index.module.scss";

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
  const router = useRouter();

  useEffect(() => {
    getSession().then(({ data }) => {
      if (data?.session) router.replace("/home");
    }).catch(() => {});
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await signin({ email, password });
      if (!res.success) {
        setError(res.error);
        return;
      }
      router.replace("/home");
    } catch {
      setError("操作失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  }

  return (
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
      <div className={styles.wrapper}>
        <div className={styles.card}>
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
              <label className={styles.label}>邮箱</label>
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
              <label className={styles.label}>密码</label>
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
              <a href="#" className={styles.forgotLink} onClick={(e) => e.preventDefault()}>
                忘记密码？
              </a>
            </div>

            {error && <p className={styles.error}>{error}</p>}

            <button type="submit" disabled={loading} className={styles.button}>
              {loading ? (
                <span className={styles.loadingRing} />
              ) : (
                "登录"
              )}
            </button>
          </form>

          <div className={styles.features}>
            {features.map((f) => (
              <div key={f.label} className={styles.feature}>
                <span className={styles.featureIcon}>{f.svg}</span>
                {f.label}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className={styles.footer}>
        &copy; {new Date().getFullYear()} AI 智能平台 &mdash; All rights reserved
      </div>
    </div>
  );
}
