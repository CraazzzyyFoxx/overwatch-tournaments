"use client";

import React from "react";

import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface ImpactBarProps {
  /** 0–100 impact / percentile. */
  value: number;
}

/** Colour ramp: high = emerald, low = rose, mid = blue (matches the design). */
function impactColor(value: number): string {
  if (value >= 66) return "var(--c-up)";
  if (value <= 34) return "var(--c-down)";
  return "var(--c-info)";
}

/** A horizontal 0–100 impact bar with the value tucked at the end. */
export default function ImpactBar({ value }: ImpactBarProps) {
  const color = impactColor(value);
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
