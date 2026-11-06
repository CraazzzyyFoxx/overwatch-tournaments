"use client";

import { useQuery } from "@tanstack/react-query";

import { adminQueryKeys } from "@/lib/admin/query-keys";
import { ALL_DISCIPLINES } from "@/lib/site/discipline-scope";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import adminService from "@/services/admin.service";
import teamService from "@/services/team.service";
import tournamentService from "@/services/tournament.service";

/**
 * What a tournament scope brings with it: the tournament itself, its stages and
 * groups, and its teams — and, while the chip picks the scope, the workspace's
 * tournaments to pick from.
 *
 * Every one of these reads is gated on a scope actually being chosen — the
 * workspace-wide browser opens with none, and four unscoped requests for
 * "every team ever" is what that used to cost. The chip's list is the
 * workspace's: it waits until the workspace is known.
 */
export function useEncounterScope({
  tournamentId,
  scopeTournamentId,
  workspaceId
}: Readonly<{
  /** Pinned by the hub; `null` means the chip picks the scope instead. */
  tournamentId: number | null;
  /** The pin, or the chip — whichever is in force. */
  scopeTournamentId: number | null;
  workspaceId: number | null;
}>) {
  const tournamentsQuery = useQuery({
    queryKey: tournamentQueryKeys.adminList(workspaceId, ALL_DISCIPLINES),
    queryFn: () => tournamentService.getAll(workspaceId),
    enabled: tournamentId == null && workspaceId != null
  });

  const tournamentQuery = useQuery({
    queryKey: adminQueryKeys.tournament(scopeTournamentId),
    queryFn: () => adminService.getTournament(scopeTournamentId!),
    enabled: scopeTournamentId != null
  });

  const stagesQuery = useQuery({
    queryKey: adminQueryKeys.stages(scopeTournamentId),
    queryFn: () => adminService.getStages(scopeTournamentId!),
    enabled: scopeTournamentId != null
  });

  const teamsQuery = useQuery({
    queryKey: tournamentQueryKeys.teams(scopeTournamentId),
    queryFn: () => teamService.getAll({ tournamentId: scopeTournamentId }),
    enabled: scopeTournamentId != null
  });

  const stages = stagesQuery.data ?? [];

  return {
    tournaments: tournamentsQuery.data?.results ?? [],
    tournament: tournamentQuery.data,
    stages,
    stageItems: stages.flatMap((stage) => stage.items),
    teams: teamsQuery.data?.results ?? []
  };
}
