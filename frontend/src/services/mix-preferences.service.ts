import { apiFetch } from "@/lib/api-fetch";

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
};

export const mixPreferencesKeys = {
  /** One row per account; the caller is always its own subject. */
  all: ["mix-preferences"] as const,
};

export const mixPreferencesService = {
  get(): Promise<MixBalancerPreferences> {
    return apiFetch("/api/balancer/me/mix-preferences").then((r) => r.json());
  },

  /** Replaces the whole row: every knob travels, `null` clearing it back to the default. */
  update(preferences: MixBalancerPreferences): Promise<MixBalancerPreferences> {
    return apiFetch("/api/balancer/me/mix-preferences", {
      method: "PUT",
      body: preferences,
    }).then((r) => r.json());
  },
};
