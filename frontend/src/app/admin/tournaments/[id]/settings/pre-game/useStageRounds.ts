"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import adminService from "@/services/admin.service";
import {
  FFA_STAGE_TYPES,
  GROUP_STAGE_TYPES,
  projectedRoundRobinRounds
} from "@/lib/bracket/projection";
import type { Stage } from "@/types/tournament.types";
import { stageRoundOptions, type PickBanScopeEncounter } from "@/lib/tournament/pick-ban-config";

export interface StageRounds {
  /** Ascending round numbers; negative ones are lower-bracket rounds. */
  rounds: number[];
  loading: boolean;
}

/**
 * The rounds of one stage: the generated ones union — for a group stage — the
 * count it is configured to play, or the server's prediction when neither is
 * known yet.
 *
 * Elimination round numbering is not guessable client-side (see
 * `stageRoundOptions`): double elimination numbers its lower bracket
 * negatively, and a single elimination's round count follows the team count
 * rather than the stage's `max_rounds`. So the server predicts it from the
 * stage's planned team inputs, running the real generator.
 *
 * A group stage is different. A Swiss plays exactly `max_rounds` (the server
 * refuses to generate past it), and a round robin plays as many rounds as its
 * largest group needs — `n - 1` for an even field, mirrored in
 * `projectedRoundRobinRounds`, which is derived from the teams wired into the
 * stage rather than from `max_rounds`. Either way the rounds are known before
 * the bracket is, which is when a group stage's per-round map pools are
 * actually authored: the prediction returns nothing until teams are wired in.
 *
 * A round robin with nothing wired yet has no derivable length, so it falls
 * back to `max_rounds` — the same planning number the best-of editor offers
 * rows for. A round the generated bracket never has is inert; a round missing
 * from this list is one nobody can configure.
 *
 * An FFA stage is fixed at one round and needs neither derivation nor a server
 * prediction: its lobbies all sit in round 1, and `best_of` sizes the series
 * inside a lobby rather than adding rounds. Without that, the pre-game scope
 * tree offered a stage with lobbies no round at all, so its map pool and
 * best-of were unauthorable.
 *
 * Shared by the scope tree and the stage editor: both need the same rounds, and
 * one query key means the second one costs nothing.
 */
export function useStageRounds(
  stage: Stage | null | undefined,
  encounters: PickBanScopeEncounter[] | undefined
): StageRounds {
  const stageId = stage?.id ?? null;
  // Stable identity: callers baseline editor state off these rounds, and a
  // fresh array every render would re-baseline the form under the organizer.
  const generated = useMemo(
    () => (stageId == null ? EMPTY_ROUNDS : stageRoundOptions(stageId, encounters)),
    [stageId, encounters]
  );
  const planned = useMemo(() => {
    if (stage == null) return EMPTY_ROUNDS;
    // An FFA stage plays ONE round: every lobby of a group is round 1, and
    // `best_of` sizes the series inside a lobby rather than adding rounds. So
    // the pre-game scope tree offers a single round to hang a map pool on,
    // instead of a row per game nobody plays in sequence. (The lobbies' kickoff
    // is a different screen: `RoundScheduleSection` reads them itself.)
    if (FFA_STAGE_TYPES.includes(stage.stage_type)) return FFA_ROUNDS;
    if (!GROUP_STAGE_TYPES.includes(stage.stage_type)) return EMPTY_ROUNDS;
    const derived =
      stage.stage_type === "round_robin" ? projectedRoundRobinRounds(stage) : 0;
    const count = derived > 0 ? derived : Math.floor(stage.max_rounds);
    return Array.from({ length: Math.max(0, count) }, (_, index) => index + 1);
  }, [stage]);

  // A Swiss is generated ONE round at a time (`_get_swiss_generation_context`
  // pairs round N+1 off round N's standings), so mid-stage its bracket holds
  // only the rounds already played -- and taking the generated list alone left
  // the tree offering Round 1 and nothing else, with rounds 2..max_rounds
  // unconfigurable until the moment they were about to be played. There the
  // generated rounds and the planned length are unioned.
  //
  // Only there: a round robin generates its whole schedule in one pass, so its
  // generated rounds ARE the stage, and `max_rounds` is an unrelated planning
  // field a union would let leak in as a round the bracket never has.
  const known = useMemo(() => {
    if (generated.length === 0) return planned;
    if (planned.length === 0 || stage?.stage_type !== "swiss") return generated;
    return [...new Set([...generated, ...planned])].sort((left, right) => left - right);
  }, [generated, planned, stage?.stage_type]);

  const predicted = useQuery({
    queryKey: ["admin", "stage", stageId, "planned-rounds"],
    queryFn: () => adminService.getStagePlannedRounds(stageId as number),
    enabled: stageId != null && known.length === 0
  });

  if (known.length > 0) return { rounds: known, loading: false };
  if (predicted.data != null && predicted.data.length > 0) {
    return { rounds: predicted.data, loading: false };
  }
  if (predicted.isPending) {
    return { rounds: EMPTY_ROUNDS, loading: stageId != null };
  }
  return { rounds: EMPTY_ROUNDS, loading: false };
}

const EMPTY_ROUNDS: number[] = [];
/** Every lobby of an FFA stage is round 1; there is no second round to author. */
const FFA_ROUNDS: number[] = [1];
