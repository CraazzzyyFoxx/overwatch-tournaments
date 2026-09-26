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
import type { SeedRanking, Stage, StageBestOfConfig, StageType } from "@/types/tournament.types";

import {
  BRACKET_STAGE_TYPES,
  FFA_STAGE_TYPES,
  defaultTiebreakOrder,
  normalizeMaxRounds
} from "@/lib/bracket/projection";

export interface StageForm {
  name: string;
  /** Phase number. Same value = parallel brackets. */
  order: number;
  stageType: StageType;
  /** Kept as strings: an empty field is "inherit", which `0` cannot express. */
  maxRounds: string;
  advanceCount: string;
  deGrandFinalType: "no_reset" | "with_reset";
  splitLowerBracket: boolean;
  seedRanking: SeedRanking;
  rankingPreset: string;
  tiebreakOrder: string[];
  scoringWin: string;
  scoringDraw: string;
  scoringLoss: string;
  swissByePoints: string;
  bestOf: StageBestOfConfig;
  /** FFA leagues: what place `i + 1` pays, `[]` for a score-only lobby. */
  ffaPlacementPoints: number[];
  ffaScorePoints: number;
  /** The organizer's word for the score column; empty keeps the default. */
  ffaScoreLabel: string;
}

const numberOrEmpty = (value: number | null) => (value != null ? String(value) : "");
const emptyOrNumber = (value: string) => (value !== "" ? Number(value) : null);

export function stageFormFromStage(stage: Stage): StageForm {
  return {
    name: stage.name,
    order: stage.order,
    stageType: stage.stage_type,
    maxRounds: String(stage.max_rounds ?? 5),
    advanceCount: numberOrEmpty(stage.advance_count),
    deGrandFinalType: stage.de_grand_final_type,
    splitLowerBracket: stage.split_lower_bracket ?? false,
    seedRanking: stage.seed_ranking,
    rankingPreset: stage.ranking_preset || "default",
    tiebreakOrder: stage.tiebreak_order ?? defaultTiebreakOrder(stage.stage_type),
    scoringWin: numberOrEmpty(stage.scoring.win),
    scoringDraw: numberOrEmpty(stage.scoring.draw),
    scoringLoss: numberOrEmpty(stage.scoring.loss),
    swissByePoints: numberOrEmpty(stage.swiss_bye_points),
    bestOf: stage.best_of,
    ffaPlacementPoints: stage.ffa_scoring.placement_points,
    ffaScorePoints: stage.ffa_scoring.score_points,
    ffaScoreLabel: stage.ffa_scoring.score_label ?? ""
  };
}

export function buildStageUpdatePayload(stage: Stage, form: StageForm): StageUpdateInput {
  const isFfa = FFA_STAGE_TYPES.includes(form.stageType);

  return {
    name: form.name.trim() || stage.name,
    order: form.order,
    stage_type: form.stageType,
    max_rounds: normalizeMaxRounds(form.maxRounds, stage.max_rounds ?? 5),
    advance_count:
      form.advanceCount !== "" ? normalizeMaxRounds(form.advanceCount, 1) : null,
    split_lower_bracket:
      form.stageType === "double_elimination" ? form.splitLowerBracket : false,
    ranking_preset: form.rankingPreset === "default" ? null : form.rankingPreset || null,
    // A metric switched off in the editor is simply absent from the list — that
    // absence IS the "disabled" state the engine reads. `points` is the one
    // exception: it cannot be turned off, and the engine forces it first if it
    // is missing, so persist the list that already says so rather than an order
    // the server would have to correct (an empty list saves as `["points"]`).
    tiebreak_order: form.tiebreakOrder.includes("points")
      ? form.tiebreakOrder
      : ["points", ...form.tiebreakOrder],
    scoring: {
      win: emptyOrNumber(form.scoringWin),
      draw: emptyOrNumber(form.scoringDraw),
      loss: emptyOrNumber(form.scoringLoss)
    },
    swiss_bye_points: emptyOrNumber(form.swissByePoints),
    de_grand_final_type:
      form.stageType === "double_elimination" ? form.deGrandFinalType : "no_reset",
    seed_ranking: BRACKET_STAGE_TYPES.includes(form.stageType) ? form.seedRanking : "slot",
    // An FFA lobby is one round of N games, and the generator resolves that count
    // as `resolve_best_of(cfg, 1, is_final=False)` — `by_round["1"]` outranks
    // `default`, and `final` is a bracket's last round. Either one left over from
    // the format this stage used to be would silently beat "Games per lobby",
    // with nothing in the editor that can reach it, so only `default` is kept.
    best_of: isFfa ? { default: form.bestOf.default, by_round: {}, final: null } : form.bestOf,
    // Only an FFA league is scored by place and raw score; any other type leaves
    // the stored table alone rather than saving a rule its format cannot use.
    ...(isFfa && {
      ffa_scoring: {
        placement_points: form.ffaPlacementPoints,
        score_points: form.ffaScorePoints,
        score_label: form.ffaScoreLabel.trim() || null
      }
    })
  };
}

/**
 * Human labels of the fields that differ from the saved stage — the `SaveBar`
 * summary, and the dirty flag itself (`length > 0`).
 */
const FIELD_LABELS: Record<keyof StageForm, string> = {
  name: "Name",
  order: "Phase",
  stageType: "Format",
  maxRounds: "Swiss rounds",
  advanceCount: "Teams advancing",
  deGrandFinalType: "Grand final",
  splitLowerBracket: "Group seeding",
  seedRanking: "Bracket seeds",
  rankingPreset: "Standings preset",
  tiebreakOrder: "Tiebreaker order",
  scoringWin: "Win points",
  scoringDraw: "Draw points",
  scoringLoss: "Loss points",
  swissByePoints: "Swiss bye points",
  bestOf: "Best-of",
  ffaPlacementPoints: "Points per place",
  ffaScorePoints: "Points per score unit",
  ffaScoreLabel: "Score label"
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
