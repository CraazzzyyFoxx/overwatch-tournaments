import type { QueryClient } from "@tanstack/react-query";

import { getTournamentWorkspaceQueryKeys } from "@/app/admin/tournaments/[id]/components/tournamentWorkspace.queryKeys";
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

export type CoalescerClock<TTimer> = {
  setTimeout: (callback: () => void, delayMs: number) => TTimer;
  clearTimeout: (timer: TTimer) => void;
};

export type Coalescer = {
  schedule: () => void;
  cancel: () => void;
};

export function createLeadingCoalescer<TTimer = ReturnType<typeof setTimeout>>(
  callback: () => void,
  windowMs: number,
  clock: CoalescerClock<TTimer> = {
    setTimeout: (scheduledCallback, scheduledDelay) =>
      setTimeout(scheduledCallback, scheduledDelay) as TTimer,
    clearTimeout: (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
  },
): Coalescer {
  let cooldownTimer: TTimer | null = null;
  let generation = 0;

  return {
    schedule: () => {
      if (cooldownTimer !== null) {
        return;
      }

      callback();
      const scheduledGeneration = generation;
      cooldownTimer = clock.setTimeout(() => {
        if (generation === scheduledGeneration) {
          cooldownTimer = null;
        }
      }, windowMs);
    },
    cancel: () => {
      generation += 1;
      if (cooldownTimer !== null) {
        clock.clearTimeout(cooldownTimer);
        cooldownTimer = null;
      }
    },
  };
}

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
    tournamentQueryKeys.heroPlaytime(tournamentId),
    tournamentQueryKeys.standings(tournamentId),
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
    tournamentQueryKeys.teams(tournamentId),
    tournamentQueryKeys.heroPlaytime(tournamentId),
    tournamentQueryKeys.standings(tournamentId),
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

function invalidateAdminTournamentQueries(
  queryClient: QueryClient,
  tournamentId: number,
  scope: TournamentRealtimeUpdatePlan["workspaceScope"],
): void {
  const keys = getTournamentWorkspaceQueryKeys(tournamentId);

  if (scope === "bracket") {
    void queryClient.invalidateQueries({ queryKey: keys.encounters });
    return;
  }

  // The metadata key is a parent of the admin workspace collections. Keep it
  // exact so each active child query is invalidated once through its own prefix.
  void queryClient.invalidateQueries({ queryKey: keys.tournament, exact: true });
  void queryClient.invalidateQueries({ queryKey: keys.stages });
  void queryClient.invalidateQueries({ queryKey: keys.standings });
  void queryClient.invalidateQueries({ queryKey: keys.encounters });
  void queryClient.invalidateQueries({ queryKey: keys.standingsTable });

  if (scope === "results") {
    void queryClient.invalidateQueries({ queryKey: keys.logHistory });
    return;
  }

  void queryClient.invalidateQueries({ queryKey: keys.teams });
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
  invalidateAdminTournamentQueries(queryClient, tournamentId, plan.workspaceScope);

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
  clock: CoalescerClock<TTimer> = {
    setTimeout: (scheduledCallback, scheduledDelay) =>
      setTimeout(scheduledCallback, scheduledDelay) as TTimer,
    clearTimeout: (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
  },
): Coalescer {
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
