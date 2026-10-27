"use client";

import React from "react";

import type { Tournament } from "@/types/tournament.types";
import { SelectContent, SelectGroup, SelectItem } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { TooltipSelect } from "@/components/ui/tooltip-select";
import { useTranslations } from "next-intl";

interface AnalyticsPickerProps {
  tournaments: Tournament[];
  tournamentId: number | null;
  loadingTournaments: boolean;
  isErrorTournaments: boolean;
  onTournamentChange: (value: string) => void;
  /** The game's own controls (its ranking picker), beside the tournament select. */
  controls?: React.ReactNode;
}

/**
 * The tournament selector (plus the game board's own controls) as a compact,
 * label-less control row in the hero's right column; each select carries a tooltip.
 */
export default function AnalyticsPicker({
  tournaments,
  tournamentId,
  loadingTournaments,
  isErrorTournaments,
  onTournamentChange,
  controls
}: Readonly<AnalyticsPickerProps>) {
  const t = useTranslations();

  return (
    <div className="flex flex-wrap items-center gap-2.5">
      {loadingTournaments ? (
        <div role="status" className="min-w-0 max-w-[27.5rem] flex-[1_1_15rem]">
          <span className="sr-only">{t("analytics.briefing.loadingTournaments")}</span>
          <Skeleton aria-hidden className="h-8 w-full" />
        </div>
      ) : (
        <TooltipSelect
          tooltip={t("analytics.briefing.tournament")}
          value={tournamentId == null ? "" : tournamentId.toString()}
          placeholder={
            isErrorTournaments ? t("analytics.briefing.errorTournaments") : t("analytics.briefing.selectTournament")
          }
          disabled={isErrorTournaments}
          size="sm"
          className="min-w-0 max-w-[27.5rem] flex-[1_1_15rem]"
          onValueChange={onTournamentChange}
        >
          <SelectContent>
            <SelectGroup>
              {tournaments.map((item) => (
                <SelectItem key={item.id} value={item.id.toString()}>
                  {item.name}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </TooltipSelect>
      )}
      {controls}
    </div>
  );
}
