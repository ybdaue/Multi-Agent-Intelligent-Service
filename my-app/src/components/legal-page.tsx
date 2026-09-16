import type { ReactNode } from "react";
import Link from "next/link";
import styles from "./legal-page.module.scss";

interface LegalPageProps {
  title: string;
  updatedAt: string;
  children: ReactNode;
}

export default function LegalPage({
  title,
  updatedAt,
  children,
}: LegalPageProps) {
  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <Link href="/login" className={styles.back}>
          &larr; 返回登录
        </Link>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.meta}>更新日期:{updatedAt}</p>
        <div className={styles.body}>{children}</div>
      </div>
    </div>
  );
}
