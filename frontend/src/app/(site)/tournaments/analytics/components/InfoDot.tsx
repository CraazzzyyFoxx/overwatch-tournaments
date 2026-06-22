"use client";

import React from "react";

import { useTranslation } from "@/i18n/LanguageContext";
import MetricTooltip from "@/app/(site)/tournaments/analytics/components/MetricTooltip";
import { GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface InfoDotProps {
  term: GlossaryTerm;
  /** Opens the full glossary sheet. When omitted the dot is hover-only. */
  onExplain?: (term: GlossaryTerm) => void;
  /** Keep out of the tab order when nested inside another clickable element. */
  focusable?: boolean;
}

/**
 * The small "ⓘ" affordance next to a metric. Hovering reveals the one-line
 * glossary explanation (via {@link MetricTooltip}); clicking opens the full
 * bottom-sheet entry when an `onExplain` handler is wired.
 */
export default function InfoDot({ term, onExplain, focusable = true }: InfoDotProps) {
  const { t } = useTranslation();
  const label = t(`analytics.glossary.${term}.label`);

  return (
    <MetricTooltip term={term} focusable={false} showIcon={false}>
      <span
        className={styles.cInfoDot}
        role={onExplain ? "button" : undefined}
        tabIndex={onExplain && focusable ? 0 : undefined}
        aria-label={onExplain ? label : undefined}
        onClick={
          onExplain
            ? (event) => {
                event.stopPropagation();
                onExplain(term);
              }
            : undefined
        }
        onKeyDown={
          onExplain
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  event.stopPropagation();
                  onExplain(term);
                }
              }
            : undefined
        }
      >
        i
      </span>
    </MetricTooltip>
  );
}
