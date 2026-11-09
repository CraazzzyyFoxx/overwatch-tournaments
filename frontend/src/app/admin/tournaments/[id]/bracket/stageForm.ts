/**
 * The stage editor's form model: one draft object per selected stage.
 *
 * `StageManager` kept twelve `Record<stageId, value>` draft maps side by side
 * and rebuilt the payload inline in an `onClick`. With the editor scoped to
 * one stage by `?stage=`, a single draft object replaces all twelve — and the
 * payload builder becomes a pure function that `SaveBar` can also ask "is this
 * dirty, and what changed?".
 *
 * The payload sends every regulation field the editor owns, each one whole:
 * the server replaces a sent field rather than merging into it.
 */
import type { StageUpdateInput } from "@/types/admin.types";
import type {
  SeedRanking,
  Stage,
  StageBestOfConfig,
  StagePairingMode,
  StageType
} from "@/types/tournament.types";
import type { FfaColumn } from "@/types/ffa.types";
import { FFA_SCORING_PRESETS } from "@/lib/ffa/scoring-presets";

import {
  BRACKET_STAGE_TYPES,
  FFA_STAGE_TYPES,
  INDIVIDUAL_SWISS_STAGE_TYPES,
  defaultTiebreakOrder,
  normalizeMaxRounds
} from "@/lib/bracket/projection";

export interface StageForm {
  name: string;
  stageType: StageType;
  /** Kept as strings: an empty field is "inherit", which `0` cannot express. */
  maxRounds: string;
  deGrandFinalType: "no_reset" | "with_reset";
  /** `individual_swiss`: how a round forms its lobbies. */
  pairingMode: StagePairingMode;
  /** `individual_swiss`: how many teams the playoff takes (each takes its role slots of the table). */
  playoffTeamCount: number;
  /** `individual_swiss`: rank a player gains per won / loses per lost encounter; 0 = off. */
  rankWinDelta: number;
  rankLossDelta: number;
  seedRanking: SeedRanking;
  rankingPreset: string;
  tiebreakOrder: string[];
  scoringWin: string;
  scoringDraw: string;
  scoringLoss: string;
  swissByePoints: string;
  /** Swiss thresholds; `null` is the switch turned off, not "inherit". */
  swissQualifyWins: number | null;
  swissEliminateLosses: number | null;
  bestOf: StageBestOfConfig;
  /** FFA leagues: what place `i + 1` pays, `[]` for a lobby places do not pay. */
  ffaPlacementPoints: number[];
  /** What a game records per team, in table order. */
  ffaColumns: FfaColumn[];
  /** The expression a game's points are computed with. */
  ffaFormula: string;
}

const numberOrEmpty = (value: number | null) => (value != null ? String(value) : "");
const emptyOrNumber = (value: string) => (value !== "" ? Number(value) : null);

/** What an FFA league scores by when its stage saved none: the `points` preset's single raw score. */
const defaultRule = FFA_SCORING_PRESETS[0];

const ffaColumnsOf = (stage: Stage) => stage.scoring.columns ?? defaultRule.columns;

export function stageFormFromStage(stage: Stage): StageForm {
  return {
    name: stage.name,
    stageType: stage.stage_type,
    maxRounds: String(stage.max_rounds ?? 5),
    deGrandFinalType: stage.de_grand_final_type,
    pairingMode: stage.pairing_mode ?? "score",
    playoffTeamCount: stage.playoff_team_count ?? 4,
    rankWinDelta: stage.rank_win_delta ?? 0,
    rankLossDelta: stage.rank_loss_delta ?? 0,
    seedRanking: stage.seed_ranking,
    rankingPreset: stage.ranking_preset || "default",
    tiebreakOrder:
      stage.tiebreak_order ?? defaultTiebreakOrder(stage.stage_type, ffaColumnsOf(stage)),
    scoringWin: numberOrEmpty(stage.scoring.win),
    scoringDraw: numberOrEmpty(stage.scoring.draw),
    scoringLoss: numberOrEmpty(stage.scoring.loss),
    swissByePoints: numberOrEmpty(stage.swiss_bye_points),
    swissQualifyWins: stage.swiss_qualify_wins,
    swissEliminateLosses: stage.swiss_eliminate_losses,
    bestOf: stage.best_of,
    ffaPlacementPoints: stage.scoring.placement_points ?? defaultRule.placementPoints,
    ffaColumns: ffaColumnsOf(stage),
    ffaFormula: stage.scoring.formula ?? defaultRule.formula
  };
}

export function buildStageUpdatePayload(stage: Stage, form: StageForm): StageUpdateInput {
  const isFfa = FFA_STAGE_TYPES.includes(form.stageType);
  const isElimination = BRACKET_STAGE_TYPES.includes(form.stageType);
  const isSwiss = form.stageType === "swiss";
  const isIndividualSwiss = INDIVIDUAL_SWISS_STAGE_TYPES.includes(form.stageType);
  // A threshold only exists on a Swiss stage, and a decisive match only while
  // its threshold is on: a switched-off one takes its best-of with it.
  const qualifyWins = isSwiss ? form.swissQualifyWins : null;
  const eliminateLosses = isSwiss ? form.swissEliminateLosses : null;

  return {
    name: form.name.trim() || stage.name,
    stage_type: form.stageType,
    max_rounds: normalizeMaxRounds(form.maxRounds, stage.max_rounds ?? 5),
    // These exist only on an individual Swiss stage; the server clears them elsewhere.
    ...(isIndividualSwiss
      ? {
          pairing_mode: form.pairingMode,
          playoff_team_count: form.playoffTeamCount,
          rank_win_delta: form.rankWinDelta,
          rank_loss_delta: form.rankLossDelta
        }
      : {}),
    ranking_preset: form.rankingPreset === "default" ? null : form.rankingPreset || null,
    // A metric switched off in the editor is simply absent from the list — that
    // absence IS the "disabled" state the engine reads. `points` is the one
    // exception: it cannot be turned off, and the engine forces it first if it
    // is missing, so persist the list that already says so rather than an order
    // the server would have to correct (an empty list saves as `["points"]`).
    tiebreak_order: form.tiebreakOrder.includes("points")
      ? form.tiebreakOrder
      : ["points", ...form.tiebreakOrder],
    swiss_bye_points: emptyOrNumber(form.swissByePoints),
    swiss_qualify_wins: qualifyWins,
    swiss_eliminate_losses: eliminateLosses,
    de_grand_final_type:
      form.stageType === "double_elimination" ? form.deGrandFinalType : "no_reset",
    seed_ranking: isElimination ? form.seedRanking : "slot",
    // Only an elimination bracket is configured per round (on its round headers). Every other format plays one
    // length everywhere, and a `by_round` or `final` left over from what the stage used to be would silently beat
    // that `default` — FFA reads it from `by_round["1"]` — with nothing in the editor that can reach it.
    // `best_of` is replaced whole: a key left out resets to null, so all are sent.
    best_of: {
      default: form.bestOf.default,
      by_round: isElimination ? form.bestOf.by_round : {},
      final: isElimination ? form.bestOf.final : null,
      swiss_qualify: qualifyWins != null ? form.bestOf.swiss_qualify : null,
      swiss_eliminate: eliminateLosses != null ? form.bestOf.swiss_eliminate : null
    },
    // Only an FFA league is scored by columns and a formula. A stage that stays
    // another type leaves its stored rule alone (`scoring` is sent whole, so
    // "alone" means sending it back as it was). A stage whose FORMAT changes sends
    // every rule field as null: the server reads that as "the new type's own
    // rule" and would otherwise keep the old `points` rule on a duel format.
    // The formula is trimmed, not otherwise touched: it is the organizer's text,
    // and the parser that refuses it also reports the position inside it.
    scoring: {
      win: emptyOrNumber(form.scoringWin),
      draw: emptyOrNumber(form.scoringDraw),
      loss: emptyOrNumber(form.scoringLoss),
      ...(isFfa
        ? {
            preset: "points" as const,
            columns: form.ffaColumns,
            placement_points: form.ffaPlacementPoints,
            formula: form.ffaFormula.trim()
          }
        : form.stageType !== stage.stage_type
          ? { preset: null, columns: null, placement_points: null, formula: null }
          : {
              preset: stage.scoring.preset,
              columns: stage.scoring.columns,
              placement_points: stage.scoring.placement_points,
              formula: stage.scoring.formula
            })
    }
  };
}

/**
 * Human labels of the fields that differ from the saved stage — the `SaveBar`
 * summary, and the dirty flag itself (`length > 0`).
 */
const FIELD_LABELS: Record<keyof StageForm, string> = {
  name: "name",
  stageType: "format",
  maxRounds: "swissRounds",
  deGrandFinalType: "grandFinal",
  pairingMode: "pairingMode",
  playoffTeamCount: "playoffTeams",
  rankWinDelta: "rankWinDelta",
  rankLossDelta: "rankLossDelta",
  seedRanking: "bracketSeeds",
  rankingPreset: "standingsPreset",
  tiebreakOrder: "tiebreakerOrder",
  scoringWin: "winPoints",
  scoringDraw: "drawPoints",
  scoringLoss: "lossPoints",
  swissByePoints: "swissByePoints",
  swissQualifyWins: "swissQualifyWins",
  swissEliminateLosses: "swissEliminateLosses",
  bestOf: "bestOf",
  ffaPlacementPoints: "pointsPerPlace",
  ffaColumns: "gameColumns",
  ffaFormula: "pointsFormula"
};

export function stageFormChanges(stage: Stage, form: StageForm): string[] {
  const saved = stageFormFromStage(stage);
  const changed: string[] = [];
  for (const key of Object.keys(FIELD_LABELS) as (keyof StageForm)[]) {
    const before = saved[key];
    const after = form[key];
    const same =
      typeof before === "object" && before !== null
        ? JSON.stringify(before) === JSON.stringify(after)
        : before === after;
    if (!same) changed.push(FIELD_LABELS[key]);
  }
  return changed;
}
