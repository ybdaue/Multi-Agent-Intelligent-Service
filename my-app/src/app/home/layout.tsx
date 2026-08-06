import { Suspense } from "react";
import { auth } from "@/lib/auth";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import Header from "./components/Header";
import styles from "./layout.module.scss";


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
  if (!session) redirect("/login");
  return <Header userName={session.user.name} userEmail={session.user.email} />;
}

export default function HomeLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.layout}>
      <Suspense fallback={<HeaderSkeleton />}>
        <HeaderSection />
      </Suspense>
      {children}
    </div>
  );
}
