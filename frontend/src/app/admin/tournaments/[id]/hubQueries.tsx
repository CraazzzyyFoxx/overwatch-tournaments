"use client";

import { useQuery } from "@tanstack/react-query";

import { Skeleton } from "@/components/ui/skeleton";
import adminService from "@/services/admin.service";
import encounterService from "@/services/encounter.service";
import teamService from "@/services/team.service";
import tournamentService from "@/services/tournament.service";
import workspaceService from "@/services/workspace.service";
import type { DivisionGridEntity, DivisionGridVersion } from "@/types/workspace.types";
import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament/workspace-query-keys";

/**
 * How often the hub refreshes its polled metrics while the tab is in front.
 * Foreground only (`refetchIntervalInBackground: false` everywhere below): the
 * hub already invalidates on realtime events and TanStack refetches on focus,
 * so a hidden tab polling every minute only bills the API for nothing.
 */
export const TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS = 60_000;

/** Shared loading fallback of every hub tab route. */
export const tabFallback = (
  <div className="space-y-4">
    <Skeleton className="h-32 w-full rounded-xl" />
    <Skeleton className="h-64 w-full rounded-xl" />
  </div>
);

/*
 * Shared query hooks of the tournament hub (T5). Keys and options MUST stay
 * in lockstep between the shell (gate + header metrics) and the tab pages —
 * realtime patch-in-cache and workspace invalidation address these exact keys
 * (see lib/tournament/workspace-query-keys.ts). TanStack Query dedupes
 * observers of the same key, so a tab page mounting a hook reuses the shell's
 * cache entry instead of refetching. The pre-T5 `enabled` tab conditions
 * (shouldLoadTeams = teams|matches, shouldLoadEncounters = matches|logs) are
 * now expressed by WHICH route pages mount each hook.
 */

export function useHubTournamentQuery(tournamentId: number) {
  return useQuery({
    queryKey: getTournamentWorkspaceQueryKeys(tournamentId).tournament,
    queryFn: () => adminService.getTournament(tournamentId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0
  });
}

export function useHubStagesQuery(tournamentId: number) {
  return useQuery({
    queryKey: getTournamentWorkspaceQueryKeys(tournamentId).stages,
    queryFn: () => adminService.getStages(tournamentId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0
  });
}

export function useHubTeamsQuery(tournamentId: number) {
  return useQuery({
    queryKey: getTournamentWorkspaceQueryKeys(tournamentId).teams,
    queryFn: () => teamService.getAll({ tournamentId }),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0
  });
}

/** Header metric only — the count endpoint, not the team list. */
export function useHubTeamsCountQuery(tournamentId: number) {
  return useQuery({
    queryKey: ["admin", "tournament", tournamentId, "teams", "count"],
    queryFn: () => teamService.getCount(tournamentId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0,
    refetchInterval: TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: false
  });
}

export function useHubEncountersQuery(tournamentId: number) {
  return useQuery({
    queryKey: getTournamentWorkspaceQueryKeys(tournamentId).encounters,
    queryFn: () => encounterService.getAll(1, "", tournamentId, -1),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0,
    refetchInterval: TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: false
  });
}

/** Header metric only — the count endpoint, not the encounter list. */
export function useHubEncountersCountQuery(tournamentId: number) {
  return useQuery({
    queryKey: ["admin", "tournament", tournamentId, "encounters", "count"],
    queryFn: () => encounterService.getCount(tournamentId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0,
    refetchInterval: TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: false
  });
}

export function useHubStandingsQuery(tournamentId: number) {
  return useQuery({
    queryKey: getTournamentWorkspaceQueryKeys(tournamentId).standings,
    queryFn: () =>
      tournamentService.getStandings(tournamentId, {
        includeMatchesHistory: false,
        includeTeamGroup: false
      }),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0,
    refetchInterval: TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: false
  });
}

export function useHubDivisionGridsQuery(
  tournamentId: number,
  workspaceId: number | null | undefined
) {
  return useQuery({
    queryKey: getTournamentWorkspaceQueryKeys(tournamentId).divisionGrids,
    queryFn: async () => {
      if (!workspaceId) return [];
      return workspaceService.getDivisionGrids(workspaceId);
    },
    enabled: Boolean(workspaceId)
  });
}

/** Newest-first flat list of grid versions, for the Settings tab grid picker. */
export function flattenDivisionGridVersions(
  grids: DivisionGridEntity[] | undefined
): DivisionGridVersion[] {
  return (grids ?? [])
    .flatMap((grid) => grid.versions)
    .slice()
    .sort((left, right) => right.version - left.version);
}

