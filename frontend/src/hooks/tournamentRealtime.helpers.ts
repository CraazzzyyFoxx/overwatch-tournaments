import type { QueryClient } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament-query-keys";

export type TournamentChangedReason =
  | "bracket_changed"
  | "results_changed"
  | "structure_changed";

type TournamentUpdatedMessage = {
  type: "tournament:updated";
  data?: {
    tournament_id?: number;
    reason?: TournamentChangedReason;
  };
};

export type TournamentRealtimeUpdatePlan = {
  workspaceScope: "bracket" | "results" | "full";
  queryKeys: readonly (readonly unknown[])[];
  shouldRefreshRoute: boolean;
};

export type TrailingCoalescerClock<TTimer> = {
  setTimeout: (callback: () => void, delayMs: number) => TTimer;
  clearTimeout: (timer: TTimer) => void;
};

export type TrailingCoalescer = {
  schedule: () => void;
  cancel: () => void;
};

export function parseTournamentRealtimeMessage(
  rawData: string,
  tournamentId: number,
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
    message.data.reason !== "bracket_changed" &&
    message.data.reason !== "structure_changed"
  ) {
    return null;
  }

  return {
    tournamentId,
    reason: message.data.reason,
  };
}

function getResultQueryPrefixes(tournamentId: number): readonly (readonly unknown[])[] {
  return [
    tournamentQueryKeys.detail(tournamentId),
    tournamentQueryKeys.stages(tournamentId),
    tournamentQueryKeys.heroPlaytime(tournamentId),
    tournamentQueryKeys.standings(tournamentId),
    tournamentQueryKeys.bracketStandings(tournamentId),
    tournamentQueryKeys.encounters(tournamentId),
  ];
}

function getParticipantQueryPrefixes(
  tournamentId: number,
  workspaceId: number | null | undefined,
): readonly (readonly unknown[])[] {
  if (workspaceId == null) {
    return [];
  }

  return [
    tournamentQueryKeys.registration(workspaceId, tournamentId),
    tournamentQueryKeys.registrationsList(workspaceId, tournamentId),
    tournamentQueryKeys.registrationForm(workspaceId, tournamentId),
  ];
}

export function getTournamentRealtimeUpdatePlan(
  tournamentId: number,
  workspaceId: number | null | undefined,
  reason: TournamentChangedReason,
): TournamentRealtimeUpdatePlan {
  if (reason === "bracket_changed") {
    return {
      workspaceScope: "bracket",
      queryKeys: [tournamentQueryKeys.encounters(tournamentId)],
      shouldRefreshRoute: false,
    };
  }

  const resultQueryPrefixes = getResultQueryPrefixes(tournamentId);
  if (reason === "results_changed") {
    return {
      workspaceScope: "results",
      queryKeys: resultQueryPrefixes,
      shouldRefreshRoute: false,
    };
  }

  return {
    workspaceScope: "full",
    queryKeys: [
      ...resultQueryPrefixes,
      tournamentQueryKeys.teams(tournamentId),
      ...getParticipantQueryPrefixes(tournamentId, workspaceId),
    ],
    shouldRefreshRoute: true,
  };
}

export function getTournamentRealtimeCatchUpPlan(
  tournamentId: number,
  workspaceId: number | null | undefined,
): readonly (readonly unknown[])[] {
  return [
    tournamentQueryKeys.detail(tournamentId),
    tournamentQueryKeys.stages(tournamentId),
    tournamentQueryKeys.teams(tournamentId),
    tournamentQueryKeys.heroPlaytime(tournamentId),
    tournamentQueryKeys.standings(tournamentId),
    tournamentQueryKeys.bracketStandings(tournamentId),
    tournamentQueryKeys.encounters(tournamentId),
    ...getParticipantQueryPrefixes(tournamentId, workspaceId),
  ];
}

function invalidateQueryPrefixes(
  queryClient: QueryClient,
  queryKeys: readonly (readonly unknown[])[],
): void {
  for (const queryKey of queryKeys) {
    void queryClient.invalidateQueries({ queryKey });
  }
}

export function applyTournamentRealtimeUpdate(
  queryClient: QueryClient,
  tournamentId: number,
  workspaceId: number | null | undefined,
  reason: TournamentChangedReason,
  onStructureChanged?: () => void,
): void {
  const plan = getTournamentRealtimeUpdatePlan(tournamentId, workspaceId, reason);
  invalidateQueryPrefixes(queryClient, plan.queryKeys);

  if (plan.shouldRefreshRoute) {
    onStructureChanged?.();
  }
}

export function applyTournamentRealtimeCatchUp(
  queryClient: QueryClient,
  tournamentId: number,
  workspaceId: number | null | undefined,
): void {
  invalidateQueryPrefixes(
    queryClient,
    getTournamentRealtimeCatchUpPlan(tournamentId, workspaceId),
  );
}

export function createTrailingCoalescer<TTimer = ReturnType<typeof setTimeout>>(
  callback: () => void,
  delayMs: number,
  clock: TrailingCoalescerClock<TTimer> = {
    setTimeout: (scheduledCallback, scheduledDelay) =>
      setTimeout(scheduledCallback, scheduledDelay) as TTimer,
    clearTimeout: (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
  },
): TrailingCoalescer {
  let timer: TTimer | null = null;
  let generation = 0;

  return {
    schedule: () => {
      generation += 1;
      const scheduledGeneration = generation;
      if (timer !== null) {
        clock.clearTimeout(timer);
      }
      timer = clock.setTimeout(() => {
        if (generation !== scheduledGeneration) {
          return;
        }
        timer = null;
        callback();
      }, delayMs);
    },
    cancel: () => {
      generation += 1;
      if (timer !== null) {
        clock.clearTimeout(timer);
        timer = null;
      }
    },
  };
}
