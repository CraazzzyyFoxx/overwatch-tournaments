import type { QueryClient } from "@tanstack/react-query";

import {
  invalidateTournamentResults,
  invalidateTournamentWorkspace,
} from "@/app/admin/tournaments/[id]/components/tournamentWorkspace.queryKeys";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";

export type TournamentChangedReason = "results_changed" | "structure_changed";

type TournamentUpdatedMessage = {
  type: "tournament:updated";
  data?: {
    tournament_id?: number;
    reason?: TournamentChangedReason;
  };
};

export type TournamentRealtimeUpdatePlan = {
  /**
   * How much of the tournament workspace to invalidate. `results` touches only
   * result-derived queries; `full` refreshes structure (teams, registrations,
   * metadata) as well.
   */
  workspaceScope: "results" | "full";
  queryKeys: readonly (readonly unknown[])[];
  shouldRefreshRoute: boolean;
};

export function parseTournamentRealtimeMessage(
  rawData: string,
  tournamentId: number
): { tournamentId: number; reason: TournamentChangedReason } | null {
  let message: TournamentUpdatedMessage;

  try {
    message = JSON.parse(rawData) as TournamentUpdatedMessage;
  } catch {
    return null;
  }

  if (
    message.type !== "tournament:updated" ||
    message.data?.tournament_id !== tournamentId
  ) {
    return null;
  }

  if (
    message.data.reason !== "results_changed" &&
    message.data.reason !== "structure_changed"
  ) {
    return null;
  }

  return {
    tournamentId,
    reason: message.data.reason,
  };
}

export function getTournamentRealtimeUpdatePlan(
  tournamentId: number,
  workspaceId: number | null | undefined,
  reason: TournamentChangedReason
): TournamentRealtimeUpdatePlan {
  if (reason === "results_changed") {
    // A score recalculation only moves result-derived data. Refetching team
    // rosters, registrations, or the tournament list here is pure waste, so the
    // results scope deliberately omits them.
    const queryKeys: (readonly unknown[])[] = [
      tournamentQueryKeys.detail(tournamentId),
      tournamentQueryKeys.stages(tournamentId),
      tournamentQueryKeys.heroPlaytime(tournamentId),
      ["standings", tournamentId],
      ["standings-table", tournamentId],
      ["encounters", "tournament", tournamentId],
    ];

    if (workspaceId != null) {
      queryKeys.push(
        ["standings", tournamentId, workspaceId],
        ["encounters", "tournament", tournamentId, workspaceId]
      );
    }

    return {
      workspaceScope: "results",
      queryKeys,
      shouldRefreshRoute: false,
    };
  }

  // structure_changed — stages, teams, registrations, or metadata changed;
  // refresh the full workspace.
  const queryKeys: (readonly unknown[])[] = [
    tournamentQueryKeys.detail(tournamentId),
    tournamentQueryKeys.stages(tournamentId),
    tournamentQueryKeys.teams(tournamentId),
    tournamentQueryKeys.heroPlaytime(tournamentId),
    ["standings", tournamentId],
    ["standings-table", tournamentId],
    ["encounters", "tournament", tournamentId],
  ];

  if (workspaceId != null) {
    queryKeys.push(
      ["standings", tournamentId, workspaceId],
      ["encounters", "tournament", tournamentId, workspaceId],
      tournamentQueryKeys.registration(workspaceId, tournamentId),
      tournamentQueryKeys.registrationsList(workspaceId, tournamentId),
      tournamentQueryKeys.registrationForm(workspaceId, tournamentId)
    );
  }

  return {
    workspaceScope: "full",
    queryKeys,
    shouldRefreshRoute: true,
  };
}

export function applyTournamentRealtimeUpdate(
  queryClient: QueryClient,
  tournamentId: number,
  workspaceId: number | null | undefined,
  reason: TournamentChangedReason,
  onStructureChanged?: () => void
): void {
  const plan = getTournamentRealtimeUpdatePlan(tournamentId, workspaceId, reason);

  if (plan.workspaceScope === "full") {
    invalidateTournamentWorkspace(queryClient, tournamentId, workspaceId);
  } else {
    invalidateTournamentResults(queryClient, tournamentId, workspaceId);
  }

  for (const queryKey of plan.queryKeys) {
    void queryClient.invalidateQueries({ queryKey });
  }

  if (plan.shouldRefreshRoute) {
    onStructureChanged?.();
  }
}
