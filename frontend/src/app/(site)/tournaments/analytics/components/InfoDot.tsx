"use client";


import { useTranslations } from "next-intl";
import MetricTooltip from "@/app/(site)/tournaments/analytics/components/MetricTooltip";
import { GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import styles from "@/app/(site)/tournaments/analytics/components/Analytics.module.css";

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
export default function InfoDot({ term, onExplain, focusable = true }: Readonly<InfoDotProps>) {
  const t = useTranslations();
  const label = t(`analytics.glossary.${term}.label`);

  // A real <button>, not a span with role="button": Enter/Space and the focus
  // ring come from the platform. With no `onExplain` the dot is hover-only, so
  // it stays a plain <span> rather than a button that does nothing.
  return (
    <MetricTooltip term={term} focusable={false} showIcon={false}>
      {onExplain ? (
        <button
          type="button"
          className={styles.cInfoDot}
          // Nested inside another clickable element, the dot keeps its click
          // target but leaves the tab order to the enclosing control.
          tabIndex={focusable ? undefined : -1}
          aria-label={label}
          onClick={(event) => {
            event.stopPropagation();
            onExplain(term);
          }}
        >
          i
        </button>
      ) : (
        <span className={styles.cInfoDot} aria-hidden>
          i
        </span>
      )}
    </MetricTooltip>
  );
}
