"use client";

import { useEffect } from "react";
import type { ServiceItem } from "@/types/service";
import ServiceCard from "../ServiceCard";
import styles from "./index.module.scss";

interface Props {
  services: ServiceItem[];
}

const SKIP_CLASS = "intro-skip";
const DOUBLE_TAP_MS = 320;
const INTRO_TOTAL_MS = 5000;

export default function ServicesGrid({ services }: Props) {
  useEffect(() => {
    const html = document.documentElement;
    let lastTap = 0;
    let timer: number;

    const stop = () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.clearTimeout(timer);
    };

    const onPointerDown = () => {
      const now = performance.now();
      if (now - lastTap < DOUBLE_TAP_MS) {
        html.classList.add(SKIP_CLASS);
        stop();
        return;
      }
      lastTap = now;
    };

    window.addEventListener("pointerdown", onPointerDown);
    timer = window.setTimeout(stop, INTRO_TOTAL_MS);

    return () => {
      stop();
      html.classList.remove(SKIP_CLASS);
    };
  }, []);

  return (
    <div className={styles.grid}>
      {services.map((s) => (
        <ServiceCard key={s.id} service={s} />
      ))}
    </div>
  );
}
