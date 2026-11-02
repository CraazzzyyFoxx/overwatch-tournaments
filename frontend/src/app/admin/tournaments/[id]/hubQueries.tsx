"use client";

import { useQuery } from "@tanstack/react-query";

import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import adminService from "@/services/admin.service";
import encounterService from "@/services/encounter.service";
import teamService from "@/services/team.service";
import workspaceService from "@/services/workspace.service";
import type { DivisionGridEntity, DivisionGridVersion } from "@/types/workspace.types";
import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament/workspace-query-keys";
import { adminQueryKeys } from "@/lib/admin/query-keys";

/**
 * How often the hub refreshes its polled metrics while the tab is in front.
 * Foreground only (`refetchIntervalInBackground: false` everywhere below): the
 * hub already invalidates on realtime events and TanStack refetches on focus,
 * so a hidden tab polling every minute only bills the API for nothing.
 */
const TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS = 60_000;

/** Shared loading fallback of every hub tab route. */
export const tabFallback = (
  <div className="space-y-4">
    <Skeleton className="h-32 w-full rounded-xl" />
    <Skeleton className="h-64 w-full rounded-xl" />
  </div>
);

/**
 * Shared failure state of every hub tab body that needs the tournament: a
 * failed read is an error with a retry, never a blank tab.
 */
export function tabError(retry: () => unknown) {
  return <PageStateCard state="error" onAction={() => void retry()} />;
}

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

/**
 * Header metric only — the count endpoint, not the team list. Scoped to the
 * tournament's OWN workspace and held until it is known: fired alongside the
 * tournament read, apiFetch injected the admin's current workspace, and a
 * tournament of another workspace read "0 teams" until the next refetch.
 */
export function useHubTeamsCountQuery(tournamentId: number, workspaceId: number | null) {
  return useQuery({
    queryKey: adminQueryKeys.tournamentTeamsCount(tournamentId),
    queryFn: () => teamService.getCount(tournamentId, workspaceId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0 && workspaceId != null,
    refetchInterval: TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: false
  });
}

export function useHubEncountersQuery(
  tournamentId: number,
  refetchIntervalMs: number = TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS
) {
  return useQuery({
    queryKey: getTournamentWorkspaceQueryKeys(tournamentId).encounters,
    queryFn: () => encounterService.getAll(1, "", tournamentId, -1),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0,
    refetchInterval: refetchIntervalMs,
    refetchIntervalInBackground: false
  });
}

/** Header metric only — the count endpoint, not the encounter list. Scoped like the teams count. */
export function useHubEncountersCountQuery(tournamentId: number, workspaceId: number | null) {
  return useQuery({
    queryKey: adminQueryKeys.tournamentEncountersCount(tournamentId),
    queryFn: () => encounterService.getCount(tournamentId, workspaceId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0 && workspaceId != null,
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
