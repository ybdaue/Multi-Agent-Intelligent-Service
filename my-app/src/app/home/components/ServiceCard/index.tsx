import Link from "next/link";
import type { ServiceItem } from "@/types/service";
import styles from "./index.module.scss";

interface Props {
  service: ServiceItem;
}

export default function ServiceCard({ service }: Props) {
  const content = (
    <div className={`${styles.card} ${service.comingSoon ? styles.comingSoon : styles.active}`}>
      <div className={styles.icon}>{service.icon}</div>
      <h3 className={`${styles.title} ${service.comingSoon ? styles.comingSoonTitle : styles.activeTitle}`}>
        {service.title}
        {service.comingSoon && (
          <span className={styles.badge}>即将上线</span>
        )}
      </h3>
      <p className={`${styles.description} ${service.comingSoon ? styles.comingSoonDesc : styles.activeDesc}`}>
        {service.description}
      </p>
    </div>
  );

  if (service.comingSoon) return content;

  return <Link href={`/home/${service.id}`} style={{ textDecoration: "none" }}>{content}</Link>;
}
