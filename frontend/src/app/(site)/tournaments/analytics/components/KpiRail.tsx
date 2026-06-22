"use client";

import React from "react";

import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import { KpiTone, KpiVM } from "@/app/(site)/tournaments/analytics/analytics.helpers";
import { GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import InfoDot from "@/app/(site)/tournaments/analytics/components/InfoDot";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface KpiRailProps {
  kpis: KpiVM[];
  onExplain?: (term: GlossaryTerm) => void;
}

const TONE_CLASS: Record<KpiTone, string> = {
  up: styles.cToneUp,
  down: styles.cToneDown,
  warn: styles.cToneWarn,
  info: styles.cToneInfo,
  neutral: styles.cToneNeutral,
};

/**
 * The six fan-facing KPIs (climbing, dropping, watch flags, average confidence,
 * upsets, new faces) — each a value tinted by tone with an info-dot explainer.
 */
export default function KpiRail({ kpis, onExplain }: KpiRailProps) {
  const { t } = useTranslation();

  return (
    <div className={styles.cKpiRail}>
      {kpis.map((kpi) => (
        <div className={styles.cKpi} key={kpi.id}>
          <span className={styles.cKpiLabel}>
            {t(`analytics.community.kpi.${kpi.id}`)}
            <InfoDot term={kpi.glossaryTerm} onExplain={onExplain} />
          </span>
          <span className={cn(styles.cKpiVal, styles.cTnum, TONE_CLASS[kpi.tone])}>
            {kpi.display}
          </span>
          <span className={styles.cKpiSub}>{t(`analytics.community.kpi.${kpi.id}Foot`)}</span>
        </div>
      ))}
    </div>
  );
}
