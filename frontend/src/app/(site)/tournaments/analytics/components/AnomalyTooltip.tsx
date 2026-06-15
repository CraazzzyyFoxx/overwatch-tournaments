"use client";

import React from "react";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import { isAnomalyGlossaryTerm } from "../analytics-glossary";

interface AnomalyTooltipProps {
  /** Anomaly kind (``smurf`` / ``throw`` / ``troll`` / ``sandbag``); arbitrary strings fall back to a capitalized label. */
  kind: string;
  /** Per-flag evidence lines from the detector, shown as secondary detail. */
  reasons?: string[];
  /** The visible trigger (the anomaly chip or badge). */
  children: React.ReactNode;
  /**
   * Whether the trigger is its own tab stop. Default true. Set false when the
   * tooltip sits inside another interactive element (e.g. a clickable row) to
   * avoid a focusable-inside-interactive accessibility violation.
   */
  focusable?: boolean;
  side?: "top" | "bottom" | "left" | "right";
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

/**
 * Hover/focus tooltip that decodes an anomaly tag into plain language. Replaces
 * the raw native ``title=`` tooltip: it leads with the friendly glossary label
 * and one-sentence explanation, then lists the specific signals that tripped the
 * flag. Copy comes from the shared ``analytics.glossary`` entries, so it stays in
 * sync with {@link AnomalyLegend}.
 */
export default function AnomalyTooltip({
  kind,
  reasons,
  children,
  focusable = true,
  side = "top",
}: AnomalyTooltipProps) {
  const { t } = useTranslation();
  const isKnown = isAnomalyGlossaryTerm(kind);
  const label = isKnown ? t(`analytics.glossary.${kind}.label`) : capitalize(kind);
  const plain = isKnown ? t(`analytics.glossary.${kind}.plain`) : null;

  // Backend emits reason CODES (e.g. "top_impact"); localise them. Legacy raw
  // dev-strings (e.g. "impact_score=82.3 >= p80", "deterministic review rule")
  // from not-yet-recomputed data are hidden rather than shown verbatim.
  const displayReasons = (reasons ?? [])
    .map((code): string | null => {
      const trimmed = (code ?? "").trim();
      if (!trimmed) return null;
      const key = `analytics.anomalyReason.${trimmed}`;
      const localised = t(key);
      if (localised !== key) return localised;
      // Unknown / legacy: drop anything that looks like a raw metric expression.
      if (/[=<>]|\brule\b|\banomaly\b|\bmethod\b|changepoint|rolling|\bp\d/i.test(trimmed)) {
        return null;
      }
      return trimmed;
    })
    .filter((r): r is string => r !== null);

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            {...(focusable ? { tabIndex: 0 } : {})}
            aria-label={plain ? `${label}: ${plain}` : label}
            className="inline-flex cursor-help items-center align-middle"
          >
            {children}
          </span>
        </TooltipTrigger>
        <TooltipContent
          side={side}
          className="max-w-[260px] border border-border bg-popover text-popover-foreground"
        >
          <span className="block text-xs font-semibold">{label}</span>
          {plain ? (
            <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
              {plain}
            </span>
          ) : null}
          {displayReasons.length > 0 ? (
            <div className="mt-1.5 border-t border-border/60 pt-1.5">
              <span className="block text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
                {t("analytics.glossary.reasonsLabel")}
              </span>
              <ul className="mt-0.5 space-y-0.5">
                {displayReasons.map((reason, index) => (
                  <li
                    key={`${reason}-${index}`}
                    className="text-xs leading-relaxed text-muted-foreground"
                  >
                    {reason}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
