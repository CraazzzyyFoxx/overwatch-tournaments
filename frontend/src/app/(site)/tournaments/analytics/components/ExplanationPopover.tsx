"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Info } from "lucide-react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import analyticsService from "@/services/analytics.service";

interface ExplanationPopoverProps {
  playerId: number;
  tournamentId: number;
  algorithmId?: number;
}

function formatFeatureValue(value: number | null): string | null {
  if (value === null || value === undefined) return null;
  if (Number.isInteger(value)) return value.toString();
  return value.toFixed(1);
}

/** Fallback when a feature has no translation: "final_blows_p10" → "Final blows / 10 min". */
function humanizeFeature(feature: string, per10minSuffix: string): string {
  const base = feature.endsWith("_p10") ? feature.slice(0, -4) : feature;
  const words = base.replace(/_/g, " ").trim();
  const capitalized = words.charAt(0).toUpperCase() + words.slice(1);
  return feature.endsWith("_p10") ? `${capitalized}${per10minSuffix}` : capitalized;
}

/**
 * Per-player explanation popover. Instead of raw model feature names and SHAP
 * numbers, it tells a normal reader, in plain language, which stats pushed the
 * impact score up or down versus the average for the player's role.
 */
export default function ExplanationPopover({
  playerId,
  tournamentId,
  algorithmId,
}: ExplanationPopoverProps) {
  const t = useTranslations();
  const [open, setOpen] = React.useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["analytics-explanation", playerId, tournamentId, algorithmId],
    queryFn: () =>
      analyticsService.getPlayerExplanation(playerId, tournamentId, algorithmId),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  });

  const featureLabel = (feature: string): string => {
    // Runtime-dynamic feature name: assert it's a valid message key (next-intl
    // types keys as literal unions; the humanize fallback below still runs).
    const translated = t(`analytics.features.${feature}` as Parameters<typeof t>[0]);
    return translated === `analytics.features.${feature}`
      ? humanizeFeature(feature, t("analytics.features.per10minSuffix"))
      : translated;
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          title={t("analytics.explanation.trigger")}
          aria-label={t("analytics.explanation.trigger")}
        >
          <Info className="h-4 w-4" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="end">
        {isLoading && (
          <p className="text-sm text-muted-foreground">{t("analytics.explanation.loading")}</p>
        )}
        {isError && (
          <p className="text-sm text-muted-foreground">
            {t("analytics.explanation.unavailable")}
          </p>
        )}
        {data && (
          <div className="space-y-2">
            <header>
              <p className="text-sm font-semibold">{t("analytics.explanation.title")}</p>
              <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                {t("analytics.explanation.subtitle")}
              </p>
            </header>
            <ul className="space-y-1.5 text-xs">
              {data.contributions.slice(0, 5).map((contribution) => {
                const raised = contribution.shap >= 0;
                const value = formatFeatureValue(contribution.value);
                return (
                  <li
                    key={contribution.feature}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="min-w-0 truncate text-foreground">
                      {featureLabel(contribution.feature)}
                      {value != null ? (
                        <span className="ml-1 tabular-nums text-muted-foreground">{value}</span>
                      ) : null}
                    </span>
                    <span
                      className={cn(
                        "inline-flex shrink-0 items-center gap-0.5 rounded px-1 py-0.5 font-medium",
                        raised ? "text-emerald-300" : "text-rose-300",
                      )}
                    >
                      {raised ? (
                        <ArrowUp className="h-3 w-3" aria-hidden="true" />
                      ) : (
                        <ArrowDown className="h-3 w-3" aria-hidden="true" />
                      )}
                      {raised
                        ? t("analytics.explanation.raised")
                        : t("analytics.explanation.lowered")}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
