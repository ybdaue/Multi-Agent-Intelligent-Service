"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import Link from "next/link";
import type { ServiceItem } from "@/types/service";
import styles from "./index.module.scss";

/* 随机值只能在浏览器里产生，用 layout effect 保证在首帧绘制前写入，避免动画跳变 */
const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

interface Props {
  service: ServiceItem;
}

export default function ServiceCard({ service }: Props) {
  const dropRef = useRef<HTMLDivElement>(null);

  useIsoLayoutEffect(() => {
    const el = dropRef.current;
    if (!el) return;
    // 弹跳高度 0.7~1.5 倍；摆动角度 0.6~1.4 倍，方向随机
    const dir = Math.random() < 0.5 ? -1 : 1;
    el.style.setProperty("--bounce", (0.7 + Math.random() * 0.8).toFixed(2));
    el.style.setProperty("--wobble", (dir * (0.6 + Math.random() * 0.8)).toFixed(2));
  }, []);

  const content = (
    <div className={`${styles.card} ${service.comingSoon ? styles.comingSoon : styles.active}`}>
      <div className={styles.head}>
        <div className={styles.icon}>{service.icon}</div>
        <h3 className={`${styles.title} ${service.comingSoon ? styles.comingSoonTitle : styles.activeTitle}`}>
          {service.title}
          {service.comingSoon && (
            <span className={styles.badge}>即将上线</span>
          )}
        </h3>
      </div>
      <p className={`${styles.description} ${service.comingSoon ? styles.comingSoonDesc : styles.activeDesc}`}>
        {service.description}
      </p>
    </div>
  );

  return (
    <div className={styles.slot}>
      <div className={styles.drop} ref={dropRef}>
        {service.comingSoon ? (
          content
        ) : (
          <Link href={`/home/${service.id}`} className={styles.link}>
            {content}
          </Link>
        )}
      </div>
    </div>
  );
}
