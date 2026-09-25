"use client";

import { useEffect, useRef } from "react";

const TRAIL_LENGTH = 10;
const SMOOTHING = 0.2;

export default function MouseTrail() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (window.matchMedia("(pointer: coarse)").matches) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const pts = Array.from({ length: TRAIL_LENGTH + 2 }, () => ({ x: -100, y: -100 }));
    const mouse = { x: -100, y: -100 };
    let raf: number;

    const resize = () => {
      canvas!.width = window.innerWidth;
      canvas!.height = window.innerHeight;
    };
    resize();
    window.addEventListener("resize", resize);

    const onMove = (e: MouseEvent) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
    };
    window.addEventListener("mousemove", onMove);

    /* 暗色/亮色调色板：暗色用紫蓝，亮色用天蓝 */
    function palette(dark: boolean) {
      return dark
        ? { hR: 165, hG: 180, hB: 252, tR: 168, tG: 85, tB: 247 }
        : { hR: 147, hG: 197, hB: 253, tR: 191, tG: 219, tB: 254 };
    }

    const animate = () => {
      ctx!.clearRect(0, 0, canvas!.width, canvas!.height);

      /* 头两个点紧贴鼠标 */
      pts[0].x += (mouse.x - pts[0].x) * 0.45;
      pts[0].y += (mouse.y - pts[0].y) * 0.45;
      pts[1].x += (pts[0].x - pts[1].x) * 0.35;
      pts[1].y += (pts[0].y - pts[1].y) * 0.35;

      for (let i = 2; i < TRAIL_LENGTH + 2; i++) {
        const ease = 0.2 - (i / (TRAIL_LENGTH + 2)) * 0.1;
        pts[i].x += (pts[i - 1].x - pts[i].x) * ease;
        pts[i].y += (pts[i - 1].y - pts[i].y) * ease;
      }

      const { hR, hG, hB, tR, tG, tB } = palette(
        document.documentElement.classList.contains("dark"),
      );

      /* ── 发光层 ── */
      for (let i = 0; i < TRAIL_LENGTH + 1; i++) {
        const t = i / (TRAIL_LENGTH + 1);
        const width = (1 - t) * 18 + 1;
        const alpha = Math.pow(1 - t, 1.8) * 0.3;
        const mix = t;
        const r = Math.round(hR + (tR - hR) * mix);
        const g = Math.round(hG + (tG - hG) * mix);
        const b = Math.round(hB + (tB - hB) * mix);

        ctx!.beginPath();
        ctx!.moveTo(pts[i].x, pts[i].y);
        ctx!.lineTo(pts[i + 1].x, pts[i + 1].y);
        ctx!.lineWidth = width;
        ctx!.lineCap = "round";
        ctx!.strokeStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
        ctx!.stroke();
      }

      /* ── 主光晕层 ── */
      for (let i = 0; i < TRAIL_LENGTH + 1; i++) {
        const t = i / (TRAIL_LENGTH + 1);
        const width = (1 - t) * 8 + 0.5;
        const alpha = Math.pow(1 - t, 1.4) * 0.6;
        const mix = t;
        const r = Math.round(hR + (tR - hR) * mix);
        const g = Math.round(hG + (tG - hG) * mix);
        const b = Math.round(hB + (tB - hB) * mix);

        ctx!.beginPath();
        ctx!.moveTo(pts[i].x, pts[i].y);
        ctx!.lineTo(pts[i + 1].x, pts[i + 1].y);
        ctx!.lineWidth = width;
        ctx!.lineCap = "round";
        ctx!.strokeStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
        ctx!.stroke();
      }

      /* ── 核心亮线 ── */
      for (let i = 0; i < TRAIL_LENGTH + 1; i++) {
        const t = i / (TRAIL_LENGTH + 1);
        const width = (1 - t) * 3 + 0.3;
        const alpha = Math.pow(1 - t, 1.2) * 0.85;
        const mix = t;
        const r = Math.round(Math.min(255, hR + (tR - hR) * mix + 50));
        const g = Math.round(Math.min(255, hG + (tG - hG) * mix + 50));
        const b = Math.round(Math.min(255, hB + (tB - hB) * mix + 50));

        ctx!.beginPath();
        ctx!.moveTo(pts[i].x, pts[i].y);
        ctx!.lineTo(pts[i + 1].x, pts[i + 1].y);
        ctx!.lineWidth = width;
        ctx!.lineCap = "round";
        ctx!.strokeStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
        ctx!.stroke();
      }

      raf = requestAnimationFrame(animate);
    };
    raf = requestAnimationFrame(animate);

    return () => {
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", onMove);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{ position: "fixed", inset: 0, zIndex: 9999, pointerEvents: "none" }}
    />
  );
}