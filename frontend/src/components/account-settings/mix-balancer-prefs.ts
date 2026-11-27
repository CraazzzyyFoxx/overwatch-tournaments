import type { MixBalancerPreferences, MixRatingMode } from "@/services/mix-preferences.service";

/**
 * What a stored mix preference means, as the settings panel edits it. Pure
 * functions, no React: the panel holds the draft, this decides what a draft
 * means and what gets stored.
 *
 * Storing a default is avoided on purpose -- a knob left where the engine
 * would have put it anyway is stored as `null`, so "never touched" stays
 * distinguishable from "deliberately set to the default", and an account that
 * never opened this panel keeps an empty row.
 */

/** The engine's own weighting: rank balance and role comfort weigh the same. */
export const DEFAULT_COMFORT_TILT = 0.5;

/** A role nobody weighted counts exactly once in the role-line balance term. */
export const DEFAULT_ROLE_WEIGHT = 1;

/** Widest weight the server accepts (`RoleSettings.mix_weight`). */
export const MAX_ROLE_WEIGHT = 100;

/**
 * What one mix run hands back when nobody asked for a number -- the server's
 * own `solver.MIX_RESULT_VARIANTS`, which is also the ceiling it accepts
 * (`AlgorithmConfig.max_result_variants`).
 */
export const DEFAULT_RESULT_VARIANTS = 100;
export const MAX_RESULT_VARIANTS = DEFAULT_RESULT_VARIANTS;

/** Ceiling the server enforces on the rank-adjustment-per-win. */
export const MAX_POINTS_PER_WIN = 1000;

/** The lane-matchup rule as the balancer defaults it; `weight` and `cohesion` are 0..`MAX_LANE_WEIGHT`. */
export const DEFAULT_LANE_RULE = { enabled: true, weight: 0.5, cohesion: 0.25 };
export const MAX_LANE_WEIGHT = 10;

/** Stored lane rule, each field clamped; a missing rule or field reads as its default. */
function laneRuleOf(preferences: MixBalancerPreferences | null | undefined): MixPrefsDraft["laneRule"] {
  const stored = preferences?.mix_rules?.lane_matchup;
  const weight = (value: unknown, fallback: number) =>
    typeof value === "number" && Number.isFinite(value)
      ? Math.min(MAX_LANE_WEIGHT, Math.max(0, value))
      : fallback;
  return {
    enabled: typeof stored?.enabled === "boolean" ? stored.enabled : DEFAULT_LANE_RULE.enabled,
    weight: weight(stored?.weight, DEFAULT_LANE_RULE.weight),
    cohesion: weight(stored?.cohesion_weight, DEFAULT_LANE_RULE.cohesion),
  };
}

/** Stored tilt, clamped to the range the server enforces. */
function tiltOf(preferences: MixBalancerPreferences | null | undefined): number {
  const stored = preferences?.mix_comfort_tilt;
  if (typeof stored !== "number" || !Number.isFinite(stored)) {
    return DEFAULT_COMFORT_TILT;
  }
  return Math.min(1, Math.max(0, stored));
}

/** Stored weights, with anything unusable dropped rather than rendered as NaN. */
function roleWeightsOf(
  preferences: MixBalancerPreferences | null | undefined,
): Record<string, number> {
  const stored = {
    ...preferences?.role_settings,
    ...(preferences?.open_slot_settings ? { flex: preferences.open_slot_settings } : {}),
  };
  return Object.fromEntries(
    Object.entries(stored).flatMap(([code, settings]): [string, number][] => {
      const weight = settings?.mix_weight;
      return typeof weight === "number" && Number.isFinite(weight) && weight >= 0
        ? [[code, weight]]
        : [];
    }),
  );
}

/** Stored option count, clamped; unset reads as the engine's own number. */
function variantsOf(preferences: MixBalancerPreferences | null | undefined): number {
  const stored = preferences?.max_result_variants;
  if (typeof stored !== "number" || !Number.isFinite(stored)) {
    return DEFAULT_RESULT_VARIANTS;
  }
  return Math.min(MAX_RESULT_VARIANTS, Math.max(1, Math.round(stored)));
}


/** Stored points-per-win; `null` (and a stored `0`) means the knob is off. */
function pointsPerWinOf(
  preferences: MixBalancerPreferences | null | undefined,
): number | null {
  const stored = preferences?.points_per_win;
  if (typeof stored !== "number" || !Number.isFinite(stored) || stored <= 0) {
    return null;
  }
  return Math.min(MAX_POINTS_PER_WIN, Math.round(stored));
}

/** A weight set back to the default drops out of the map instead of being stored. */
export function withRoleWeight(
  weights: Record<string, number>,
  code: string,
  weight: number | null,
): Record<string, number> {
  const next = { ...weights };
  if (weight == null || weight === DEFAULT_ROLE_WEIGHT) {
    delete next[code];
    return next;
  }
  next[code] = Math.min(MAX_ROLE_WEIGHT, Math.max(0, weight));
  return next;
}

/** Every knob as the panel holds it, before it becomes a stored row. */
export type MixPrefsDraft = {
  tilt: number;
  weights: Record<string, number>;
  variants: number;
  pointsPerWin: number | null;
  ratingMode: MixRatingMode;
  banPresets: Record<string, string>;
  formationDefaults: MixBalancerPreferences["formation_defaults"];
  laneRule: { enabled: boolean; weight: number; cohesion: number };
};

/** The draft a stored row (or an empty one) opens as. */
export function draftOf(preferences: MixBalancerPreferences | null | undefined): MixPrefsDraft {
  return {
    tilt: tiltOf(preferences),
    weights: roleWeightsOf(preferences),
    variants: variantsOf(preferences),
    pointsPerWin: pointsPerWinOf(preferences),
    ratingMode: preferences?.rating_mode === "ranker" ? "ranker" : "points",
    banPresets: { ...(preferences?.hero_ban_presets ?? {}) },
    formationDefaults: { ...(preferences?.formation_defaults ?? {}) },
    laneRule: laneRuleOf(preferences),
  };
}

/** The row to store: every knob travels, a default one as `null`. */
export function preferencesPayload(draft: MixPrefsDraft): MixBalancerPreferences {
  const weighted = Object.fromEntries(
    Object.entries(draft.weights)
      .filter(([code, weight]) => code !== "flex" && weight !== DEFAULT_ROLE_WEIGHT)
      .map(([code, weight]): [string, { mix_weight: number }] => [code, { mix_weight: weight }]),
  );
  // Clamped before the default check: the default IS the ceiling, so anything
  // typed past it means "the default", not a pinned copy of it.
  const variants = Math.min(MAX_RESULT_VARIANTS, Math.max(1, Math.round(draft.variants)));
  return {
    mix_comfort_tilt: draft.tilt === DEFAULT_COMFORT_TILT ? null : draft.tilt,
    role_settings: Object.keys(weighted).length > 0 ? weighted : null,
    max_result_variants: variants === DEFAULT_RESULT_VARIANTS ? null : variants,
    open_slot_settings:
      draft.weights.flex == null || draft.weights.flex === DEFAULT_ROLE_WEIGHT
        ? null
        : { mix_weight: draft.weights.flex },
    points_per_win:
      draft.pointsPerWin == null || draft.pointsPerWin <= 0
        ? null
        : Math.min(MAX_POINTS_PER_WIN, Math.round(draft.pointsPerWin)),
    // Not a knob with a default to clear: the server stores one of two modes.
    rating_mode: draft.ratingMode,
    // Sorted: the server's jsonb answers games in its own key order, and the panel compares serialized rows.
    hero_ban_presets: Object.fromEntries(
      Object.entries(draft.banPresets).sort(([left], [right]) => (left < right ? -1 : 1)),
    ),
    // Rebuilt rather than passed through: the panel compares serialized rows, so each game's own keys are ordered too.
    formation_defaults: Object.fromEntries(
      Object.entries(draft.formationDefaults)
        .sort(([left], [right]) => (left < right ? -1 : 1))
        .map(([code, { team_formation, draft_pick_seconds }]) => [code, { team_formation, draft_pick_seconds }]),
    ),
    mix_rules:
      draft.laneRule.enabled === DEFAULT_LANE_RULE.enabled &&
      draft.laneRule.weight === DEFAULT_LANE_RULE.weight &&
      draft.laneRule.cohesion === DEFAULT_LANE_RULE.cohesion
        ? null
        : {
            lane_matchup: {
              enabled: draft.laneRule.enabled,
              weight: draft.laneRule.weight,
              cohesion_weight: draft.laneRule.cohesion,
            },
          },
  };
}
