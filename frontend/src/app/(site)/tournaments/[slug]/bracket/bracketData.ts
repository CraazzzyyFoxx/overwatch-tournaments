import { queryOptions } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import encounterService from "@/services/encounter.service";
import tournamentService from "@/services/tournament.service";
import type { Encounter } from "@/types/encounter.types";
import type { Stage, StageSummary, Tournament, TournamentStatus } from "@/types/tournament.types";

/** One team slot of one cached encounter, as the optimistic swap names it. */
export interface SlotAddress {
  encounterId: number;
  slot: "home" | "away";
}

/**
 * The cached encounter list after two slots exchange teams — what the server's
 * `swap-slot` will return, applied ahead of it so the dropped team lands where
 * it was dropped instead of snapping back for a round trip. Handles the
 * same-encounter flip (home ↔ away) and leaves every other row untouched.
 */
export function swapSlotTeams(
  encounters: readonly Encounter[],
  source: SlotAddress,
  target: SlotAddress
): Encounter[] {
  const read = (encounter: Encounter, slot: "home" | "away") =>
    slot === "home"
      ? { id: encounter.home_team_id, team: encounter.home_team }
      : { id: encounter.away_team_id, team: encounter.away_team };
  const write = (encounter: Encounter, slot: "home" | "away", value: { id: number; team: Encounter["home_team"] }) =>
    slot === "home"
      ? { ...encounter, home_team_id: value.id, home_team: value.team }
      : { ...encounter, away_team_id: value.id, away_team: value.team };

  const sourceRow = encounters.find((encounter) => encounter.id === source.encounterId);
  const targetRow = encounters.find((encounter) => encounter.id === target.encounterId);
  if (!sourceRow || !targetRow) return [...encounters];
  const fromSource = read(sourceRow, source.slot);
  const fromTarget = read(targetRow, target.slot);

  return encounters.map((encounter) => {
    let next = encounter;
    if (encounter.id === source.encounterId) next = write(next, source.slot, fromTarget);
    if (encounter.id === target.encounterId) next = write(next, target.slot, fromSource);
    return next;
  });
}

export function getBracketRefetchInterval(status: TournamentStatus): number | false {
  return status === "live" || status === "playoffs" ? 15_000 : false;
}

/**
 * Whether a stage's bracket is visible to this viewer. Admins see every
 * stage, including an organizer's un-activated preview (`is_published=
 * false`); everyone else only sees stages that are published or already
 * finished -- a preview stays hidden from spectators until it goes live.
 */
export function isStageVisibleToViewer(stage: StageSummary, isAdmin: boolean): boolean {
  return isAdmin || stage.is_published || stage.is_completed;
}

/**
 * Whether a captain report action is available for an encounter's stage. A
 * bracket generated ahead of activation (`is_published=false`, not yet
 * `is_completed`) is a preview: the backend rejects the report regardless
 * (`shared.services.bracket.usability.is_encounter_live`), so the report
 * action must not appear as available here either. `undefined` (stage not
 * yet loaded, or a scrim encounter with no stage) defaults to reportable so
 * a data-loading race never hides a legitimate action.
 */
export function isStageReportable(stage: StageSummary | undefined): boolean {
  return stage === undefined || stage.is_published || stage.is_completed;
}

function requestedStageId(value: string | null): number | null {
  if (value == null || !/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

function selectBracketStageId(
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
          includeMatchesHistory: true,
          includeTeamGroup: true
        }),
      enabled: hasTournament && hasStage,
      refetchInterval,
      refetchIntervalInBackground: false
    })
  };
}

interface BracketQuerySnapshot {
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
