"use client";

import React from "react";
import { ArrowDown, ArrowUp } from "lucide-react";

import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface DeltaPillProps {
  /** predicted_place − actual_place; + = overperformed, − = underperformed. */
  delta: number | null;
}

/**
 * A team's over/under-performance pill: green "+N" when it finished better than
 * forecast, rose "−N" when worse, a neutral "on form" when bang on.
 */
export default function DeltaPill({ delta }: DeltaPillProps) {
  const { t } = useTranslation();
  if (delta == null) return null;

  if (delta === 0) {
    return (
      <span className={cn(styles.cDelta, styles.cDeltaFlat)}>
        {t("analytics.community.standings.onForm")}
      </span>
    );
  }

  const up = delta > 0;
  return (
    <span className={cn(styles.cDelta, up ? styles.cDeltaUp : styles.cDeltaDown)}>
      {up ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
      {up ? "+" : "−"}
      {Math.abs(delta)}
    </span>
  );
}
