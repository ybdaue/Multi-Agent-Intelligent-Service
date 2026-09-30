"use client";

import dynamic from "next/dynamic";

const AdminLayoutClient = dynamic(() => import("./AdminLayoutClient"), { ssr: false });

export default function AdminLayoutDynamic({ children, role }: { children: React.ReactNode; role: string }) {
  return <AdminLayoutClient role={role}>{children}</AdminLayoutClient>;
}