"use client";

import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useCallback } from "react";
import styles from "../page.module.scss";

interface PaginationProps {
  page: number;
  total: number;
  pageSize: number;
}

export function Pagination({ page, total, pageSize }: PaginationProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const totalPages = Math.ceil(total / pageSize);

  const goToPage = useCallback(
    (p: number) => {
      const params = new URLSearchParams(searchParams.toString());
      if (p <= 1) {
        params.delete("page");
      } else {
        params.set("page", String(p));
      }
      const qs = params.toString();
      router.push(qs ? `?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  return (
    <div className={styles.pagination}>
      <button disabled={page <= 1} onClick={() => goToPage(page - 1)}>
        上一页
      </button>
      <span>
        第 {page} / {totalPages || 1} 页 (共 {total} 条)
      </span>
      <button disabled={page >= totalPages} onClick={() => goToPage(page + 1)}>
        下一页
      </button>
    </div>
  );
}
