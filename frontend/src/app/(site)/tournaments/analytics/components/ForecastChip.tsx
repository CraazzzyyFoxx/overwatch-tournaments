"use client";

import React from "react";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import { confidenceWord, formatAnalyticsNumber } from "../analytics.helpers";

export type ForecastDirection = "promote" | "demote" | "flat";

interface ForecastChipProps {
  direction: ForecastDirection;
  /** Magnitude of the move (absolute), e.g. divisions or places. */
  magnitude?: number;
  /** Unit label after the magnitude; defaults to the translated "div". */
  unit?: string;
  /** Model confidence 0–1; rendered as a plain word (High/Medium/Low). */
  confidence?: number;
  /** Extra raw numbers shown inside the tooltip. */
  rawTooltip?: React.ReactNode;
  className?: string;
  /**
   * Whether the chip is its own tab stop. Default true. Set false inside another
   * interactive element (e.g. a clickable standings row).
   */
  focusable?: boolean;
}

const DIRECTION_META: Record<
  ForecastDirection,
  { key: "up" | "down" | "hold"; cls: string; Icon: typeof ArrowUp }
> = {
  promote: { key: "up", cls: "border-emerald-500/40 text-emerald-300 bg-emerald-500/10", Icon: ArrowUp },
  demote: { key: "down", cls: "border-rose-500/40 text-rose-300 bg-rose-500/10", Icon: ArrowDown },
  flat: { key: "hold", cls: "border-border text-muted-foreground bg-muted/40", Icon: Minus },
};

const TONE_CLS: Record<"high" | "medium" | "low", string> = {
  high: "text-emerald-300",
  medium: "text-amber-300",
  low: "text-muted-foreground",
};

/**
 * One chip that says, in plain language, which way the model expects a player /
 * team to move, by how much, and how sure it is. Raw numbers stay in the
 * tooltip. All copy is translated via the `analytics.forecast` namespace.
 */
export default function ForecastChip({
  direction,
  magnitude,
  unit,
  confidence,
  rawTooltip,
  className,
  focusable = true,
}: ForecastChipProps) {
  const t = useTranslations();
  const meta = DIRECTION_META[direction];
  const { Icon } = meta;
  const label = t(`analytics.forecast.${meta.key}`);
  const resolvedUnit = unit ?? t("analytics.forecast.divisionUnit");
  const conf = confidence != null ? confidenceWord(confidence) : null;
  const confLabel = conf ? t(`analytics.confidence.${conf.tone}`) : null;
  const hasMove = direction !== "flat" && magnitude != null && magnitude > 0;
  const magnitudeText = hasMove ? `${formatAnalyticsNumber(magnitude!, 1)} ${resolvedUnit}` : label;
  const ariaLabel = [
    label,
    hasMove ? t("analytics.forecast.by", { magnitude: formatAnalyticsNumber(magnitude!, 1), unit: resolvedUnit }) : null,
    confLabel ? t("analytics.forecast.confidence", { label: confLabel }) : null,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            {...(focusable ? { tabIndex: 0 } : {})}
            aria-label={ariaLabel}
            className={cn(
              "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-semibold tabular-nums",
              meta.cls,
              className,
            )}
          >
            <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
            <span>{magnitudeText}</span>
            {confLabel ? (
              <span className={cn("font-normal opacity-90", TONE_CLS[conf!.tone])}>· {confLabel}</span>
            ) : null}
          </span>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          className="max-w-[240px] border border-border bg-popover text-popover-foreground"
        >
          <span className="block text-xs font-semibold">{label}</span>
          {hasMove ? (
            <span className="mt-0.5 block text-xs text-muted-foreground">
              {t("analytics.forecast.by", {
                magnitude: formatAnalyticsNumber(magnitude!, 1),
                unit: resolvedUnit,
              })}
            </span>
          ) : null}
          {confLabel ? (
            <span className="mt-0.5 block text-xs text-muted-foreground">
              {t("analytics.forecast.confidenceWithPct", {
                label: confLabel,
                pct: Math.round((confidence ?? 0) * 100),
              })}
            </span>
          ) : null}
          {rawTooltip ? (
            <span className="mt-1 block text-[11px] text-muted-foreground/80">{rawTooltip}</span>
          ) : null}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
