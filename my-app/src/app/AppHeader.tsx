import { Suspense } from "react";
import { auth } from "@/lib/auth";
import { headers } from "next/headers";
import Header from "@/components/Header";

export const dynamic = "force-dynamic";

function HeaderSkeleton() {
  return (
    <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", height: 60, padding: "0 24px", background: "var(--color-bg)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 32 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 36, height: 36, borderRadius: 8, background: "var(--color-border)" }} />
          <span style={{ fontWeight: 600, fontSize: 16 }}>AI 智能平台</span>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{ width: 60, height: 32, borderRadius: 6, background: "var(--color-border)" }} />
      </div>
    </header>
  );
}

async function HeaderSection() {
  const session = await auth.api.getSession({ headers: await headers() });

  if (!session) return null;

  const role = (session.user as { role?: string }).role ?? "user";
  const isAdmin = role === "admin" || role === "superAdmin";

  return <Header userName={session.user.name} userEmail={session.user.email} isAdmin={isAdmin} />;
}

export default function AppHeader() {
  return (
    <Suspense fallback={<HeaderSkeleton />}>
      <HeaderSection />
    </Suspense>
  );
}