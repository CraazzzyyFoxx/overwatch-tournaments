/**
 * The Overwatch competitive ladder, read from a generated artifact.
 *
 * The ladder is written down once, in `backend/shared/domain/ow_ladder.py`. This
 * module holds NO ladder facts and NO rank arithmetic — it is a typed accessor
 * over `ow-ladder.generated.json`, which `backend/scripts/export_ow_ladder.py`
 * emits with everything already resolved: the 45 tiers and the full native
 * division+tier → rank_value table.
 *
 * Why an artifact and not a fetch: the default division grid has to resolve
 * synchronously during SSR and the first client render (the workspace store
 * persists only `currentWorkspaceId` and fetches the workspace, which carries the
 * real grid, in a client effect). An API round-trip cannot fill that window.
 *
 * Why an artifact and not a hand-written mirror: nothing here can drift. The JSON
 * is committed and `export_ow_ladder.py --check` fails CI when it goes stale, so
 * adding or re-anchoring a division means editing `LADDER` on the backend and
 * re-running the exporter. Nothing to keep in sync by hand.
 */

import generated from "./ow-ladder.generated.json";

export interface LadderTier {
  /** 1-based from the top of the ladder (1 = Champion 1, 45 = Bronze 5). */
  number: number;
  /**
   * Division-grid identity (`champion-1` … `bronze-5`): tier names and icon
   * filenames are built from it, and stored DB rows carry these strings.
   */
  slug: string;
  name: string;
  rank_min: number;
  /** `null` on the single open-ended tier at the top of the ladder. */
  rank_max: number | null;
  icon_url: string;
}

/** Sub-tiers per division, tier 1 the top and tier `TIERS_PER_DIVISION` the bottom. */
const TIERS_PER_DIVISION: number = generated.tiers_per_division;

/** Site-relative directory of the default OW2 rank icons (`bronze-5.png` … `champion-1.png`). */
export const DIVISION_ICON_BASE: string = generated.division_icon_base;

/**
 * Native OverFast division names, highest first — `ultimate` where the division
 * grid says `champion`. The two never meet: the OverFast name is only ever a key
 * yielding a `rank_value`, and the bridge back to a grid tier is numeric.
 */
export const OW_DIVISIONS_DESC: readonly string[] = generated.ow_divisions_desc;

/** Every sub-tier of the ladder, top (Champion 1) to bottom (Bronze 5). */
export const LADDER_TIERS: readonly LadderTier[] = generated.tiers;

/** Sub-tier numbers, `1 … TIERS_PER_DIVISION`. */
export const TIER_NUMBERS: readonly number[] = Array.from(
  { length: TIERS_PER_DIVISION },
  (_, index) => index + 1
);

const OW_RANK_VALUES: Record<string, number> = generated.ow_rank_values;

/**
 * `rank_value` for a native OverFast division + tier, or `null` for a division
 * the ladder does not carry.
 */
export function owRankValue(division: string, tier: number): number | null {
  return OW_RANK_VALUES[`${division.toLowerCase()}-${tier}`] ?? null;
}
