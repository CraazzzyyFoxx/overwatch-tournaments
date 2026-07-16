import { queryOptions } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import encounterService from "@/services/encounter.service";
import tournamentService from "@/services/tournament.service";
import type { Stage, StageSummary, Tournament, TournamentStatus } from "@/types/tournament.types";

export function getBracketRefetchInterval(status: TournamentStatus): number | false {
  return status === "live" || status === "playoffs" ? 15_000 : false;
}

function requestedStageId(value: string | null): number | null {
  if (value == null || !/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

export function selectBracketStageId(
  stages: readonly StageSummary[],
  selectedStageParam: string | null
): number | null {
  const requestedId = requestedStageId(selectedStageParam);
  const requested =
    requestedId == null ? undefined : stages.find((stage) => stage.id === requestedId);
  const active = stages.find((stage) => stage.is_active);
  const elimination = stages.find(
    (stage) =>
      stage.stage_type === "single_elimination" || stage.stage_type === "double_elimination"
  );

  return requested?.id ?? active?.id ?? elimination?.id ?? stages[0]?.id ?? null;
}

export function createBracketQueryPlan(
  tournament: Tournament,
  selectedStageParam: string | null,
  fullStages?: readonly Stage[]
) {
  const availableStages = fullStages ?? tournament.stages;
  const initialStageId = selectBracketStageId(availableStages, selectedStageParam);
  const hasTournament = Number.isSafeInteger(tournament.id) && tournament.id > 0;
  const hasStage = initialStageId != null;
  const refetchInterval = getBracketRefetchInterval(tournament.status);

  return {
    initialStageId,
    stages: queryOptions({
      queryKey: tournamentQueryKeys.stages(tournament.id),
      queryFn: () => tournamentService.getStages(tournament.id),
      enabled: hasTournament
    }),
    encounters: queryOptions({
      queryKey: tournamentQueryKeys.encounters(tournament.id, tournament.workspace_id),
      queryFn: () =>
        encounterService.getAll(
          1,
          "",
          tournament.id,
          -1,
          undefined,
          undefined,
          tournament.workspace_id
        ),
      enabled: hasTournament && hasStage,
      refetchInterval,
      refetchIntervalInBackground: false
    }),
    standings: queryOptions({
      queryKey: tournamentQueryKeys.bracketStandings(tournament.id, tournament.workspace_id),
      queryFn: () =>
        tournamentService.getStandings(tournament.id, {
          workspaceId: tournament.workspace_id,
          includeMatchesHistory: false,
          includeTeamGroup: false
        }),
      enabled: hasTournament && hasStage,
      refetchInterval,
      refetchIntervalInBackground: false
    })
  };
}

export interface BracketQuerySnapshot {
  hasData: boolean;
  isPending: boolean;
  isError: boolean;
  isFetching: boolean;
}

interface BracketLoadInput {
  hasStageId: boolean;
  stages: BracketQuerySnapshot;
  encounters: BracketQuerySnapshot;
  standings: BracketQuerySnapshot;
}

export type BracketLoadState =
  | { kind: "initial-loading"; isUpdating: boolean }
  | { kind: "initial-error"; isUpdating: boolean }
  | { kind: "refresh-error"; isUpdating: boolean }
  | { kind: "ready"; isUpdating: boolean };

export function deriveBracketLoadState(input: BracketLoadInput): BracketLoadState {
  const relevantQueries = input.hasStageId
    ? [input.stages, input.encounters, input.standings]
    : [input.stages];
  const isUpdating = relevantQueries.some((query) => query.isFetching);

  if (relevantQueries.some((query) => query.isError && !query.hasData)) {
    return { kind: "initial-error", isUpdating };
  }

  if (relevantQueries.some((query) => query.isPending && !query.hasData)) {
    return { kind: "initial-loading", isUpdating };
  }

  if (relevantQueries.some((query) => query.isError)) {
    return { kind: "refresh-error", isUpdating };
  }

  return { kind: "ready", isUpdating };
}
