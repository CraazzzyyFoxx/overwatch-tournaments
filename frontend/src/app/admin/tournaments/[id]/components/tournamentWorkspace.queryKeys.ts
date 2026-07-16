import type { QueryClient } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament-query-keys";

export function getTournamentWorkspaceQueryKeys(tournamentId: number) {
  return {
    tournament: ["admin", "tournament", tournamentId] as const,
    teams: ["admin", "tournament", tournamentId, "teams"] as const,
    divisionGrids: ["admin", "tournament", tournamentId, "division-grids"] as const,
    standings: ["admin", "tournament", tournamentId, "standings"] as const,
    standingsTable: ["standings-table", tournamentId] as const,
    encounters: ["admin", "tournament", tournamentId, "encounters"] as const,
    stages: ["admin", "stages", tournamentId] as const,
    discordChannel: ["admin", "tournament", tournamentId, "discord-channel"] as const,
    logHistory: ["admin", "tournament", tournamentId, "log-history"] as const,
    // Public collections consumed by non-admin pages (the bracket view reads
    // these; without invalidation the public grid goes stale after admin edits).
    tournaments: ["tournaments"] as const,
    teamsCollection: ["teams"] as const,
    encountersCollection: ["encounters"] as const,
    standingsCollection: ["standings"] as const,
    publicTournament: tournamentQueryKeys.detail(tournamentId),
    publicStages: tournamentQueryKeys.stages(tournamentId),
    publicTeams: tournamentQueryKeys.teams(tournamentId),
    publicHeroPlaytime: tournamentQueryKeys.heroPlaytime(tournamentId),
    publicStandings: ["standings", tournamentId] as const,
    publicEncounters: ["encounters", "tournament", tournamentId] as const
  };
}

/**
 * Invalidate every query that depends on a tournament's stages, standings,
 * encounters, or teams. Use after any admin mutation that can affect the
 * bracket view — ensures the public page matches the admin workspace
 * (Phase F consolidation of tournament workspace invalidation).
 */
export function invalidateTournamentWorkspace(
  queryClient: QueryClient,
  tournamentId: number,
  workspaceId?: number | null
): void {
  const keys = getTournamentWorkspaceQueryKeys(tournamentId);

  const invalidations = [
    queryClient.invalidateQueries({ queryKey: keys.tournament }),
    queryClient.invalidateQueries({ queryKey: keys.teams }),
    queryClient.invalidateQueries({ queryKey: keys.standings }),
    queryClient.invalidateQueries({ queryKey: keys.encounters }),
    queryClient.invalidateQueries({ queryKey: keys.stages }),
    queryClient.invalidateQueries({ queryKey: keys.tournaments }),
    queryClient.invalidateQueries({ queryKey: keys.teamsCollection }),
    queryClient.invalidateQueries({ queryKey: keys.encountersCollection }),
    queryClient.invalidateQueries({ queryKey: keys.standingsCollection }),
    queryClient.invalidateQueries({ queryKey: keys.publicTournament }),
    queryClient.invalidateQueries({ queryKey: keys.publicStages }),
    queryClient.invalidateQueries({ queryKey: keys.publicTeams }),
    queryClient.invalidateQueries({ queryKey: keys.publicHeroPlaytime }),
    queryClient.invalidateQueries({ queryKey: keys.publicStandings }),
    queryClient.invalidateQueries({ queryKey: keys.publicEncounters })
  ];

  if (workspaceId != null) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: ["standings", tournamentId, workspaceId] }),
      queryClient.invalidateQueries({
        queryKey: ["encounters", "tournament", tournamentId, workspaceId],
      }),
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registration(workspaceId, tournamentId),
      }),
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationsList(workspaceId, tournamentId),
      }),
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationForm(workspaceId, tournamentId),
      })
    );
  }

  void Promise.all(invalidations);
}

/**
 * Invalidate only the queries derived from match results (standings, encounters,
 * hero playtime, stage-completion flags). Use for a `results_changed` realtime
 * nudge: a score recalculation never alters team rosters, registrations, or the
 * tournament list, so those are deliberately left untouched to avoid refetching
 * data that did not change.
 */
export function invalidateTournamentResults(
  queryClient: QueryClient,
  tournamentId: number,
  workspaceId?: number | null
): void {
  const keys = getTournamentWorkspaceQueryKeys(tournamentId);

  const invalidations = [
    queryClient.invalidateQueries({ queryKey: keys.tournament }),
    queryClient.invalidateQueries({ queryKey: keys.standings }),
    queryClient.invalidateQueries({ queryKey: keys.encounters }),
    queryClient.invalidateQueries({ queryKey: keys.stages }),
    queryClient.invalidateQueries({ queryKey: keys.logHistory }),
    queryClient.invalidateQueries({ queryKey: keys.standingsCollection }),
    queryClient.invalidateQueries({ queryKey: keys.encountersCollection }),
    queryClient.invalidateQueries({ queryKey: keys.publicTournament }),
    queryClient.invalidateQueries({ queryKey: keys.publicStages }),
    queryClient.invalidateQueries({ queryKey: keys.publicHeroPlaytime }),
    queryClient.invalidateQueries({ queryKey: keys.publicStandings }),
    queryClient.invalidateQueries({ queryKey: keys.publicEncounters })
  ];

  if (workspaceId != null) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: ["standings", tournamentId, workspaceId] }),
      queryClient.invalidateQueries({
        queryKey: ["encounters", "tournament", tournamentId, workspaceId]
      })
    );
  }

  void Promise.all(invalidations);
}

/**
 * Invalidate only encounter collections after an encounter write commits.
 * Standings and stage completion flags are intentionally left alone until the
 * asynchronous tournament recalculation publishes `results_changed`.
 */
export function invalidateTournamentBracket(
  queryClient: QueryClient,
  tournamentId: number,
  workspaceId?: number | null
): void {
  const keys = getTournamentWorkspaceQueryKeys(tournamentId);

  const invalidations = [
    queryClient.invalidateQueries({ queryKey: keys.encounters }),
    queryClient.invalidateQueries({ queryKey: keys.encountersCollection }),
    queryClient.invalidateQueries({ queryKey: keys.publicEncounters })
  ];

  if (workspaceId != null) {
    invalidations.push(
      queryClient.invalidateQueries({
        queryKey: ["encounters", "tournament", tournamentId, workspaceId]
      })
    );
  }

  void Promise.all(invalidations);
}
