import { Suspense } from "react";
import { auth } from "@/lib/auth";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { services } from "@/lib/server/home/services-data";
import ServicesGrid from "./components/ServicesGrid";
import styles from "./page.module.scss";

async function UserGreeting() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) redirect("/login");
  return <h1 className={styles.heading}>你好，{session.user.name ?? "用户"}</h1>;
}

export default function Home() {
  return (
    <>
      <div className={styles.bgShapes}>
        <div className={styles.shape1} />
        <div className={styles.shape2} />
        <div className={styles.shape3} />
      </div>
      <main className={styles.main}>
        <div className={styles.hero}>
          <Suspense fallback={<h1 className={styles.heading}>你好，...</h1>}>
            <UserGreeting />
          </Suspense>
          <p className={styles.subtitle}>今天想用 AI 做什么？</p>
        </div>

        <ServicesGrid services={services} />
      </main>
    </>
  );
}
