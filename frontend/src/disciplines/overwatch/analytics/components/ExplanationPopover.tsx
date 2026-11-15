"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Info } from "lucide-react";
import { useTranslations } from "next-intl";

import { Popover, PopoverContent, PopoverTrigger } from "@craazzzyyfoxx/admin-kit/ui/popover";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { useFormatter } from "@/lib/datetime/client";
import analyticsService from "@/services/analytics.service";
import { analyticsQueryKeys } from "@/lib/analytics/query-keys";

interface ExplanationPopoverProps {
  playerId: number;
  tournamentId: number;
  algorithmId?: number;
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
}: Readonly<ExplanationPopoverProps>) {
  const t = useTranslations();
  const format = useFormatter();
  const [open, setOpen] = React.useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: analyticsQueryKeys.explanation(playerId, tournamentId, algorithmId),
    queryFn: () =>
      analyticsService.getPlayerExplanation(playerId, tournamentId, algorithmId),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          title={t("analytics.explanation.trigger")}
          aria-label={t("analytics.explanation.trigger")}
        >
          <Info aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="end">
        {isLoading && (
          <div role="status" className="space-y-2">
            <span className="sr-only">{t("analytics.explanation.loading")}</span>
            {[0, 1, 2].map((row) => (
              <Skeleton key={row} aria-hidden className="h-4 w-full" />
            ))}
          </div>
        )}
        {isError && (
          <p className="text-caption text-[color:var(--aqt-fg-muted)]">
            {t("analytics.explanation.unavailable")}
          </p>
        )}
        {data && (
          <div className="space-y-2">
            <header>
              <p className="text-body font-semibold text-[color:var(--aqt-fg)]">
                {t("analytics.explanation.title")}
              </p>
              <p className="mt-0.5 text-caption text-[color:var(--aqt-fg-muted)]">
                {t("analytics.explanation.subtitle")}
              </p>
            </header>
            <ul className="space-y-1.5 text-caption">
              {data.contributions.slice(0, 5).map((contribution) => {
                const raised = contribution.shap >= 0;
                // Runtime feature name: next-intl types keys as literals. An
                // untranslated one reads as a generic stat, never the raw key.
                const key = `analytics.features.${contribution.feature}` as Parameters<typeof t>[0];
                return (
                  <li
                    key={contribution.feature}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="min-w-0 truncate text-[color:var(--aqt-fg)]">
                      {t.has(key) ? t(key) : t("analytics.explanation.otherFeature")}
                      {contribution.value != null ? (
                        <span className="aqt-tnum ml-1 text-[color:var(--aqt-fg-dim)]">
                          {format.number(contribution.value, { maximumFractionDigits: 1 })}
                        </span>
                      ) : null}
                    </span>
                    <span
                      className="inline-flex shrink-0 items-center gap-0.5 font-medium"
                      style={{ color: raised ? "var(--aqt-up)" : "var(--aqt-rose)" }}
                    >
                      {raised ? (
                        <ArrowUp className="size-3.5" aria-hidden="true" />
                      ) : (
                        <ArrowDown className="size-3.5" aria-hidden="true" />
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
