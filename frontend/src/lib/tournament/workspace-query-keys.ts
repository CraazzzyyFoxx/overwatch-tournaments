import type { QueryClient } from "@tanstack/react-query";

import { adminQueryKeys } from "@/lib/admin/query-keys";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

/**
 * The bundle of keys one tournament's admin writes stale, composed from the
 * domain factories rather than respelling them: the browsers that read
 * `["admin", "tournament", id]` and the public pages that read
 * `["encounters", "tournament", id]` build those same tuples from
 * `adminQueryKeys` / `tournamentQueryKeys`, so a rename cannot desynchronize a
 * reader from the write that is supposed to refresh it.
 */
export function getTournamentWorkspaceQueryKeys(tournamentId: number) {
  return {
    tournament: adminQueryKeys.tournament(tournamentId),
    teams: adminQueryKeys.tournamentTeams(tournamentId),
    divisionGrids: ["admin", "tournament", tournamentId, "division-grids"] as const,
    standings: adminQueryKeys.tournamentStandings(tournamentId),
    standingsTable: ["standings-table", tournamentId] as const,
    encounters: adminQueryKeys.tournamentEncounters(tournamentId),
    stages: adminQueryKeys.stages(tournamentId),
    discordChannel: ["admin", "tournament", tournamentId, "discord-channel"] as const,
    readiness: ["admin", "tournament", tournamentId, "readiness"] as const,
    logHistory: ["admin", "tournament", tournamentId, "log-history"] as const,
    // Public collections consumed by non-admin pages (the bracket view reads
    // these; without invalidation the public grid goes stale after admin edits).
    tournaments: tournamentQueryKeys.list(),
    teamsCollection: tournamentQueryKeys.teamsAll(),
    encountersCollection: encounterQueryKeys.all(),
    standingsCollection: tournamentQueryKeys.standingsAll(),
    publicTournament: tournamentQueryKeys.detail(tournamentId),
    publicStages: tournamentQueryKeys.stages(tournamentId),
    publicTeams: tournamentQueryKeys.teams(tournamentId),
    publicHeroPlaytime: tournamentQueryKeys.heroPlaytime(tournamentId),
    publicStandings: tournamentQueryKeys.standings(tournamentId),
    publicEncounters: tournamentQueryKeys.encounters(tournamentId)
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
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.standings(tournamentId, workspaceId),
      }),
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.encounters(tournamentId, workspaceId),
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
