/**
 * The stage editor's form model: one draft object per selected stage.
 *
 * `StageManager` kept twelve `Record<stageId, value>` draft maps side by side
 * and rebuilt the payload inline in an `onClick`. With the editor scoped to
 * one stage by `?stage=`, a single draft object replaces all twelve — and the
 * payload builder becomes a pure function that `SaveBar` can also ask "is this
 * dirty, and what changed?".
 *
 * The payload shape is deliberately unchanged from the pre-redesign
 * `Save override` handler: same fields, same "delete the key rather than send
 * undefined" rules, same `settings_json` spread over the stage's existing keys.
 */
import type { StageBestOfConfig, StageUpdateInput } from "@/types/admin.types";
import type { Stage, StageType } from "@/types/tournament.types";
import { parseStageBestOf } from "@/lib/best-of";

import {
  BRACKET_STAGE_TYPES,
  buildBestOfSettings,
  defaultTiebreakOrder,
  normalizeMaxRounds,
  type SeedRanking,
  type StageSettings
} from "./projection";

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
}

export function stageFormFromStage(stage: Stage): StageForm {
  const settings = (stage.settings_json ?? {}) as StageSettings;
  const seedRanking =
    settings.seed_ranking === "avg_sr" ||
    settings.seed_ranking === "total_sr" ||
    settings.seed_ranking === "random"
      ? settings.seed_ranking
      : "slot";

  return {
    name: stage.name,
    order: stage.order,
    stageType: stage.stage_type,
    maxRounds: String(stage.max_rounds ?? 5),
    advanceCount: stage.advance_count != null ? String(stage.advance_count) : "",
    deGrandFinalType: settings.de_grand_final_type ?? "no_reset",
    splitLowerBracket: stage.split_lower_bracket ?? false,
    seedRanking,
    rankingPreset: settings.ranking_preset || "default",
    tiebreakOrder: settings.tiebreak_order ?? defaultTiebreakOrder(stage.stage_type),
    scoringWin: settings.scoring?.win != null ? String(settings.scoring.win) : "",
    scoringDraw: settings.scoring?.draw != null ? String(settings.scoring.draw) : "",
    scoringLoss: settings.scoring?.loss != null ? String(settings.scoring.loss) : "",
    swissByePoints: settings.swiss_bye_points != null ? String(settings.swiss_bye_points) : "",
    bestOf: parseStageBestOf(settings)
  };
}

export function buildStageUpdatePayload(stage: Stage, form: StageForm): StageUpdateInput {
  const scoring: NonNullable<StageSettings["scoring"]> = {};
  if (form.scoringWin !== "") scoring.win = Number(form.scoringWin);
  if (form.scoringDraw !== "") scoring.draw = Number(form.scoringDraw);
  if (form.scoringLoss !== "") scoring.loss = Number(form.scoringLoss);

  const settings: StageSettings = {
    ...((stage.settings_json ?? {}) as StageSettings),
    ranking_preset: form.rankingPreset === "default" ? undefined : form.rankingPreset || undefined,
    // A metric switched off in the editor is simply absent from the list — that
    // absence IS the "disabled" state the engine reads. `points` is the one
    // exception: it cannot be turned off, and the engine forces it first if it
    // is missing, so persist the list that already says so rather than an order
    // the server would have to correct (an empty list saves as `["points"]`).
    tiebreak_order: form.tiebreakOrder.includes("points")
      ? form.tiebreakOrder
      : ["points", ...form.tiebreakOrder],
    scoring: Object.keys(scoring).length > 0 ? scoring : undefined,
    swiss_bye_points: form.swissByePoints !== "" ? Number(form.swissByePoints) : undefined
  };

  if (!settings.ranking_preset) delete settings.ranking_preset;
  if (!settings.scoring) delete settings.scoring;
  if (settings.swiss_bye_points === undefined) delete settings.swiss_bye_points;

  if (form.stageType === "double_elimination") {
    settings.de_grand_final_type = form.deGrandFinalType;
  } else {
    delete settings.de_grand_final_type;
  }

  if (BRACKET_STAGE_TYPES.includes(form.stageType) && form.seedRanking !== "slot") {
    settings.seed_ranking = form.seedRanking;
  } else {
    delete settings.seed_ranking;
  }

  const bestOf = buildBestOfSettings(form.bestOf);
  if (bestOf) settings.best_of = bestOf;
  else delete settings.best_of;

  return {
    name: form.name.trim() || stage.name,
    order: form.order,
    stage_type: form.stageType,
    max_rounds: normalizeMaxRounds(form.maxRounds, stage.max_rounds ?? 5),
    advance_count:
      form.advanceCount !== "" ? normalizeMaxRounds(form.advanceCount, 1) : null,
    split_lower_bracket:
      form.stageType === "double_elimination" ? form.splitLowerBracket : false,
    settings_json: settings
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
  bestOf: "Best-of"
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
