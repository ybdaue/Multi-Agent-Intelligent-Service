"use client";

import { useRouter } from "next/navigation";

function ArrowLeftIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 12H5" />
      <path d="m12 19-7-7 7-7" />
    </svg>
  );
}

interface BackButtonProps {
  className?: string;
}

export default function BackButton({ className }: BackButtonProps) {
  const router = useRouter();
  return (
    <div className={className} onClick={() => router.push("/home/finance/stock")} aria-label="返回列表">
      <ArrowLeftIcon />
    </div>
  );
}
