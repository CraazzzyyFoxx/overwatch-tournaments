"use client";

import React from "react";

import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import { KpiId, KpiTone, KpiVM } from "@/app/(site)/tournaments/analytics/analytics.helpers";
import { GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import InfoDot from "@/app/(site)/tournaments/analytics/components/InfoDot";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface KpiRailProps {
  kpis: KpiVM[];
  onExplain?: (term: GlossaryTerm) => void;
  /** Click-through that filters the standings (climbers/upsets → movers, etc.). */
  onSelect?: (id: KpiId) => void;
}

/** KPIs that map onto a standings filter; the rest stay non-interactive. */
const KPI_FILTERS = new Set<KpiId>(["climbing", "dropping", "upsets", "watch"]);

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
export default function KpiRail({ kpis, onExplain, onSelect }: KpiRailProps) {
  const t = useTranslations();

  return (
    <div className={styles.cKpiRail}>
      {kpis.map((kpi) => {
        const filterable = onSelect != null && KPI_FILTERS.has(kpi.id);
        return (
          <div
            className={cn(styles.cKpi, filterable && styles.cKpiClickable)}
            key={kpi.id}
            role={filterable ? "button" : undefined}
            tabIndex={filterable ? 0 : undefined}
            onClick={filterable ? () => onSelect!(kpi.id) : undefined}
            onKeyDown={
              filterable
                ? (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect!(kpi.id);
                    }
                  }
                : undefined
            }
          >
            <span className={styles.cKpiLabel}>
              {t(`analytics.community.kpi.${kpi.id}`)}
              {/* On a clickable card the dot stays hover-only (no nested button);
                  on a static card it opens the full glossary sheet. */}
              <InfoDot term={kpi.glossaryTerm} onExplain={filterable ? undefined : onExplain} />
            </span>
            <span className={cn(styles.cKpiVal, styles.cTnum, TONE_CLASS[kpi.tone])}>
              {kpi.display}
            </span>
            <span className={styles.cKpiSub}>{t(`analytics.community.kpi.${kpi.id}Foot`)}</span>
          </div>
        );
      })}
    </div>
  );
}
