import { Suspense } from "react";
import styles from "./page.module.scss";
import StockView from "./components/stock-section";
import ChatWidget from "./components/chat-widget";

function PageSkeleton() {
  return (
    <div className={styles.stockView}>
      <div className={styles.skeletonBar}>
        <div style={{ width: 140 }} />
        <div style={{ width: 140 }} />
        <div style={{ width: 140 }} />
      </div>
      <div className={styles.scrollArea}>
        <table className={styles.stockTable}>
          <thead>
            <tr>
              {Array.from({ length: 8 }).map((_, i) => (
                <th key={i}>
                  <div className={styles.skeletonTh} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: 10 }).map((_, i) => (
              <tr key={i}>
                {Array.from({ length: 8 }).map((_, j) => (
                  <td key={j}>
                    <div className={styles.skeletonTd} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function StockPage() {
  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <Suspense fallback={<PageSkeleton />}>
          <StockView />
        </Suspense>
        <Suspense fallback={null}>
          <ChatWidget />
        </Suspense>
      </div>
    </div>
  );
}
