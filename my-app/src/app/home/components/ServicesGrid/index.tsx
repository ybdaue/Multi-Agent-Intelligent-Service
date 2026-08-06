import type { ServiceItem } from "@/types/service";
import ServiceCard from "../ServiceCard";
import styles from "./index.module.scss";

interface Props {
  services: ServiceItem[];
}

export default function ServicesGrid({ services }: Props) {
  return (
    <div className={styles.grid}>
      {services.map((s) => (
        <ServiceCard key={s.id} service={s} />
      ))}
    </div>
  );
}
