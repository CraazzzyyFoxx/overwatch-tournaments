import type { RosterSlotCode } from "@/lib/roster-shape";
import type { MixBalancerConfig } from "@/services/custom-game.service";

/**
 * The two knobs of `settings.balancer_config` the mix engine reads, as the
 * settings dialog edits them. Pure functions, no React: the dialog holds the
 * draft, this decides what a draft means and what gets stored.
 *
 * Storing a default is avoided on purpose -- a mix whose config equals the
 * engine defaults stores `null`, so "never touched" stays distinguishable from
 * "deliberately set to the default" in the audit log and on the wire.
 */

/** The engine's own weighting: rank balance and role comfort weigh the same. */
export const DEFAULT_COMFORT_TILT = 0.5;

/** A role nobody weighted counts exactly once in the role-line balance term. */
export const DEFAULT_ROLE_WEIGHT = 1;

/** Widest weight the server accepts (`ConfigOverrides.mix_role_weights`). */
export const MAX_ROLE_WEIGHT = 100;

/** Display names for the slot codes, matching the roster-shape vocabulary. */
export const SLOT_LABELS: Record<RosterSlotCode, string> = {
  tank: "Tank",
  dps: "Damage",
  support: "Support",
  flex: "Flex",
};

/** Stored tilt, clamped to the range the server enforces. */
export function tiltOf(config: MixBalancerConfig | null | undefined): number {
  const stored = config?.mix_comfort_tilt;
  if (typeof stored !== "number" || !Number.isFinite(stored)) {
    return DEFAULT_COMFORT_TILT;
  }
  return Math.min(1, Math.max(0, stored));
}

/** Stored weights, with anything unusable dropped rather than rendered as NaN. */
export function roleWeightsOf(config: MixBalancerConfig | null | undefined): Record<string, number> {
  const stored = config?.mix_role_weights;
  if (stored == null || typeof stored !== "object") {
    return {};
  }
  return Object.fromEntries(
    Object.entries(stored).filter(
      ([, weight]) => typeof weight === "number" && Number.isFinite(weight) && weight >= 0,
    ),
  );
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

/**
 * The blob to store: the mix's current overrides with the two mix keys applied.
 *
 * Merged rather than replaced because `custom.set_balancer_config` overwrites
 * the whole blob -- anything a host set through the API would otherwise vanish
 * the first time they opened this dialog.
 */
export function mixConfigPatch(
  current: MixBalancerConfig | null | undefined,
  tilt: number,
  weights: Record<string, number>,
): MixBalancerConfig | null {
  const merged: MixBalancerConfig = { ...(current ?? {}) };

  if (tilt === DEFAULT_COMFORT_TILT) {
    delete merged.mix_comfort_tilt;
  } else {
    merged.mix_comfort_tilt = tilt;
  }

  const weighted = Object.fromEntries(
    Object.entries(weights).filter(([, weight]) => weight !== DEFAULT_ROLE_WEIGHT),
  );
  if (Object.keys(weighted).length === 0) {
    delete merged.mix_role_weights;
  } else {
    merged.mix_role_weights = weighted;
  }

  return Object.keys(merged).length > 0 ? merged : null;
}
