"use client";

import { getImpactColor } from "@/lib/colors";
import styles from "@/app/(site)/tournaments/analytics/components/Analytics.module.css";

interface ImpactBarProps {
  /** 0–100 impact / percentile. */
  value: number;
}

/** A horizontal 0–100 impact bar with the value tucked at the end. */
export default function ImpactBar({ value }: Readonly<ImpactBarProps>) {
  const color = getImpactColor(value);
  return (
    <span className={styles.cImpact}>
      <span className={styles.cImpactTrack}>
        <span
          className={styles.cImpactFill}
          style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: color }}
        />
      </span>
      <span className={styles.cImpactNum} style={{ color }}>
        {value}
      </span>
    </span>
  );
}
