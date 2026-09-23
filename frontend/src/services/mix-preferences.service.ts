import { apiFetch } from "@/lib/api/fetch";
import type { RosterShape, RosterSlotMap } from "@/lib/roster/shape";

/**
 * The mix engine's knobs, held per account rather than per mix.
 *
 * A host runs the same pickup night the same way every week, so these lived on
 * the wrong object: stored per mix they had to be re-set (or cloned) for every
 * new game, and every mix carried its own copy of the same three numbers.
 * They belong to the person balancing, and a mix balances with the knobs of
 * the host it belongs to -- the same account whose rank book it already
 * resolves against.
 *
 * `null` everywhere means "not set": the engine's own default applies, and
 * nothing is stored.
 */
export type MixBalancerPreferences = {
  /**
   * Trade-off between rank balance and role comfort: `0` splits ranks as
   * evenly as possible, `1` maximises players seated on a preferred role.
   */
  mix_comfort_tilt: number | null;
  /** Per-line importance for the role-line balance term, keyed by roster slot code. */
  mix_role_weights: Record<string, number> | null;
  /** How many balance options one run hands back for the pager to walk. */
  max_result_variants: number | null;
  /**
   * How many slots of each kind one team gets, or `null` to follow the
   * workspace each mix runs in. Same shape a tournament pins, one level up.
   */
  role_mask: RosterSlotMap | null;
  /** Rank points a recorded win moves, in the host's own book; `null`/`0` = off. */
  points_per_win: number | null;
};

/**
 * What a read adds on top: the stored shape already resolved, so the editor can
 * render team size and draft rounds without reimplementing the server's
 * resolution. `source` is `"user"` when a shape is stored, `"default"` when the
 * account follows whatever workspace a mix runs in.
 */
export type MixBalancerPreferencesRead = MixBalancerPreferences & {
  roster_shape: RosterShape;
};

export const mixPreferencesKeys = {
  /** One row per account; the caller is always its own subject. */
  all: ["mix-preferences"] as const,
};

export const mixPreferencesService = {
  get(): Promise<MixBalancerPreferencesRead> {
    return apiFetch("/api/v1/balancer/me/mix-preferences").then((r) => r.json());
  },

  /** Replaces the whole row: every knob travels, `null` clearing it back to the default. */
  update(preferences: MixBalancerPreferences): Promise<MixBalancerPreferencesRead> {
    return apiFetch("/api/v1/balancer/me/mix-preferences", {
      method: "PUT",
      body: preferences,
    }).then((r) => r.json());
  },
};
