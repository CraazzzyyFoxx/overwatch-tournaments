import type { RosterSlotCode, RosterSlotMap } from "@/lib/roster/shape";
import type { MixBalancerPreferences } from "@/services/mix-preferences.service";

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

/** Widest weight the server accepts (`ConfigOverrides.mix_role_weights`). */
export const MAX_ROLE_WEIGHT = 100;

/**
 * What one mix run hands back when nobody asked for a number -- the server's
 * own `solver.MIX_RESULT_VARIANTS`, and the ceiling it accepts.
 */
export const DEFAULT_RESULT_VARIANTS = 500;
export const MAX_RESULT_VARIANTS = 500;

/** Ceiling the server enforces on the rank-adjustment-per-win. */
export const MAX_POINTS_PER_WIN = 1000;

/** Display names for the slot codes, matching the roster-shape vocabulary. */
export const SLOT_LABELS: Record<RosterSlotCode, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support",
  flex: "Flex",
};

/** Stored tilt, clamped to the range the server enforces. */
export function tiltOf(preferences: MixBalancerPreferences | null | undefined): number {
  const stored = preferences?.mix_comfort_tilt;
  if (typeof stored !== "number" || !Number.isFinite(stored)) {
    return DEFAULT_COMFORT_TILT;
  }
  return Math.min(1, Math.max(0, stored));
}

/** Stored weights, with anything unusable dropped rather than rendered as NaN. */
export function roleWeightsOf(
  preferences: MixBalancerPreferences | null | undefined,
): Record<string, number> {
  const stored = preferences?.mix_role_weights;
  if (stored == null || typeof stored !== "object") {
    return {};
  }
  return Object.fromEntries(
    Object.entries(stored).filter(
      ([, weight]) => typeof weight === "number" && Number.isFinite(weight) && weight >= 0,
    ),
  );
}

/** Stored option count, clamped; unset reads as the engine's own number. */
export function variantsOf(preferences: MixBalancerPreferences | null | undefined): number {
  const stored = preferences?.max_result_variants;
  if (typeof stored !== "number" || !Number.isFinite(stored)) {
    return DEFAULT_RESULT_VARIANTS;
  }
  return Math.min(MAX_RESULT_VARIANTS, Math.max(1, Math.round(stored)));
}

/** The stored roster shape override; `null` follows each mix's workspace. */
export function roleMaskOf(
  preferences: MixBalancerPreferences | null | undefined,
): RosterSlotMap | null {
  const stored = preferences?.role_mask;
  return stored != null && typeof stored === "object" ? stored : null;
}

/** Stored points-per-win; `null` (and a stored `0`) means the knob is off. */
export function pointsPerWinOf(
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
  roleMask: RosterSlotMap | null;
  pointsPerWin: number | null;
};

/** The draft a stored row (or an empty one) opens as. */
export function draftOf(preferences: MixBalancerPreferences | null | undefined): MixPrefsDraft {
  return {
    tilt: tiltOf(preferences),
    weights: roleWeightsOf(preferences),
    variants: variantsOf(preferences),
    roleMask: roleMaskOf(preferences),
    pointsPerWin: pointsPerWinOf(preferences),
  };
}

/** The row to store: every knob travels, a default one as `null`. */
export function preferencesPayload(draft: MixPrefsDraft): MixBalancerPreferences {
  const weighted = Object.fromEntries(
    Object.entries(draft.weights).filter(([, weight]) => weight !== DEFAULT_ROLE_WEIGHT),
  );
  return {
    mix_comfort_tilt: draft.tilt === DEFAULT_COMFORT_TILT ? null : draft.tilt,
    mix_role_weights: Object.keys(weighted).length > 0 ? weighted : null,
    max_result_variants:
      draft.variants === DEFAULT_RESULT_VARIANTS
        ? null
        : Math.min(MAX_RESULT_VARIANTS, Math.max(1, Math.round(draft.variants))),
    role_mask: draft.roleMask,
    points_per_win:
      draft.pointsPerWin == null || draft.pointsPerWin <= 0
        ? null
        : Math.min(MAX_POINTS_PER_WIN, Math.round(draft.pointsPerWin)),
  };
}
