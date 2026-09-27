"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Users } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import EncounterRosterPanel from "@/components/match/EncounterRosterPanel";
import encounterService from "@/services/encounter.service";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

interface EncounterRostersModalProps {
  encounterId: number;
  homeTeamName: string;
  awayTeamName: string;
}

/**
 * Both sides' rosters for a bracket match, without leaving the bracket. The
 * names on a card are 210px of truncated text; who is actually on those teams
 * meant opening the encounter page and losing the bracket's scroll position.
 *
 * Fetched lazily, on the same `["encounter-detail", id]` key the encounter page
 * and the pre-game room already use — opening this modal warms their cache
 * instead of adding a third copy of the same read.
 */
export function EncounterRostersModal({
  encounterId,
  homeTeamName,
  awayTeamName
}: Readonly<EncounterRostersModalProps>) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);

  const encounterQuery = useQuery({
    queryKey: encounterQueryKeys.detail(encounterId),
    queryFn: () => encounterService.getEncounter(encounterId),
    enabled: open
  });

  const encounter = encounterQuery.data ?? null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        className="flex items-center justify-center rounded p-0.5 text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
        aria-label={t("bracket.viewRosters")}
        onClick={(e) => {
          // Keep any future card-level click handler from also firing.
          e.stopPropagation();
        }}
      >
        <Users className="size-3.5" aria-hidden />
      </DialogTrigger>
      <DialogContent className="flex max-h-[85vh] w-[95vw] max-w-[900px] flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="shrink-0 space-y-1 border-b border-[color:var(--aqt-border)] p-4 pr-14 text-left">
          <DialogTitle>{t("bracket.rosters.title")}</DialogTitle>
          <DialogDescription>
            {t("bracket.rosters.description", { home: homeTeamName, away: awayTeamName })}
          </DialogDescription>
        </DialogHeader>
        <div className="flex-1 overflow-y-auto p-4">
          {encounterQuery.isPending ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <Skeleton className="h-72 w-full rounded-xl" />
              <Skeleton className="h-72 w-full rounded-xl" />
            </div>
          ) : encounterQuery.isError || encounter === null ? (
            <PageStateCard state="error" onAction={() => void encounterQuery.refetch()} />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              <EncounterRosterPanel
                team={encounter.home_team ?? null}
                side="home"
                tournamentGrid={encounter.tournament?.division_grid_version ?? null}
              />
              <EncounterRosterPanel
                team={encounter.away_team ?? null}
                side="away"
                tournamentGrid={encounter.tournament?.division_grid_version ?? null}
              />
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
