"use client";

import { useState, type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Users } from "lucide-react";

import { Button } from "@/components/ui/button";
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
import { seatAt } from "@/lib/encounter/seats";

interface EncounterRostersModalProps {
  encounterId: number;
  /** The two seats' names, slot 1 first. */
  teamNames: [string, string];
  /** Replaces the bracket card's icon button; must accept a ref (`asChild`). */
  trigger?: ReactElement;
}

/**
 * Both seats' rosters for a bracket match, without leaving the bracket. The
 * names on a card are 210px of truncated text; who is actually on those teams
 * meant opening the encounter page and losing the bracket's scroll position.
 *
 * Fetched lazily, on the same `["encounter-detail", id]` key the encounter page
 * and the pre-game room already use — opening this modal warms their cache
 * instead of adding a third copy of the same read.
 */
export function EncounterRostersModal({
  encounterId,
  teamNames,
  trigger
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
      {trigger ? (
        <DialogTrigger asChild>{trigger}</DialogTrigger>
      ) : (
        <DialogTrigger asChild>
          <Button
            variant="ghost"
            size="icon-xs"
            className="text-[color:var(--aqt-fg-muted)]"
            aria-label={t("bracket.viewRosters")}
            onClick={(e) => {
              // Keep any future card-level click handler from also firing.
              e.stopPropagation();
            }}
          >
            <Users aria-hidden />
          </Button>
        </DialogTrigger>
      )}
      <DialogContent variant="panel" className="max-h-[85vh] w-[95vw] max-w-[900px]">
        <DialogHeader variant="panel">
          <DialogTitle>{t("bracket.rosters.title")}</DialogTitle>
          <DialogDescription>
            {t("bracket.rosters.description", { first: teamNames[0], second: teamNames[1] })}
          </DialogDescription>
        </DialogHeader>
        <div className="flex-1 overflow-y-auto px-5 py-4">
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
                team={seatAt(encounter.teams, 1)?.team ?? null}
                slot={1}
                workspaceId={encounter.workspace_id}
                discipline={encounter.tournament.discipline}
                tournamentGrid={encounter.tournament?.division_grid_version ?? null}
              />
              <EncounterRosterPanel
                team={seatAt(encounter.teams, 2)?.team ?? null}
                slot={2}
                workspaceId={encounter.workspace_id}
                discipline={encounter.tournament.discipline}
                tournamentGrid={encounter.tournament?.division_grid_version ?? null}
              />
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
