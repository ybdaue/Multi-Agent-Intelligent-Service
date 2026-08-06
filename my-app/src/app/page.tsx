"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getSession } from "@/lib/auth-clients";

export default function Page() {
  const router = useRouter();

  useEffect(() => {
    getSession()
      .then(({ data }) => {
        router.replace(data?.session ? "/home" : "/login");
      })
      .catch(() => {
        router.replace("/login");
      });
  }, [router]);

  return null;
}
