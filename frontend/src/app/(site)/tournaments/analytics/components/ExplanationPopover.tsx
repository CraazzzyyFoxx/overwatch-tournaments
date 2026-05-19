"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import analyticsService from "@/services/analytics.service";

interface ExplanationPopoverProps {
  playerId: number;
  tournamentId: number;
  algorithmId?: number;
}

function formatShap(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(3)}`;
}

function formatFeatureValue(value: number | null): string {
  if (value === null || value === undefined) return "—";
  if (Number.isInteger(value)) return value.toString();
  return value.toFixed(3);
}

/**
 * Per-player SHAP contributions popover (Phase 5 explainability surface).
 *
 * Lazy-fetches `GET /v2/explain/player/{id}/tournament/{tid}` only when opened
 * so closed rows don't fan out into the analytics service.
 */
export default function ExplanationPopover({
  playerId,
  tournamentId,
  algorithmId,
}: ExplanationPopoverProps) {
  const [open, setOpen] = React.useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["analytics-explanation", playerId, tournamentId, algorithmId],
    queryFn: () =>
      analyticsService.getPlayerExplanation(playerId, tournamentId, algorithmId),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          title="Why this score?"
          aria-label="Show feature contributions for this player"
        >
          <Info className="h-4 w-4" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="end">
        {isLoading && (
          <p className="text-sm text-muted-foreground">Loading contributions…</p>
        )}
        {isError && (
          <p className="text-sm text-destructive">No explanation available yet.</p>
        )}
        {data && (
          <div className="space-y-2">
            <header className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium">Top feature contributions</span>
              <span className="text-xs text-muted-foreground">
                base {data.base_value.toFixed(3)}
              </span>
            </header>
            <ul className="space-y-1 text-xs">
              {data.contributions.slice(0, 5).map((c) => (
                <li
                  key={c.feature}
                  className="flex items-baseline justify-between gap-3"
                >
                  <span className="truncate">{c.feature}</span>
                  <span className="tabular-nums text-muted-foreground">
                    {formatFeatureValue(c.value)} → {formatShap(c.shap)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
