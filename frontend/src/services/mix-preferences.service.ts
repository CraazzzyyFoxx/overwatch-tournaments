import { apiFetch } from "@/lib/api/fetch";

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
  /** Per-role mix knobs keyed by roster slot code; `mix_weight` is this term's
   * per-line importance in the role-line balance. */
  role_settings: Record<string, { mix_weight: number }> | null;
  /** How many balance options one run hands back for the pager to walk. */
  max_result_variants: number | null;
  /** Weights for open slots, separate from role weights. */
  open_slot_settings: { mix_weight: number } | null;
  /** Rank points a recorded win moves, in the host's own book; `null`/`0` = off. */
  points_per_win: number | null;
  /**
   * How a recorded result moves the host's rank book. `"points"` is the flat
   * `points_per_win` above; `"ranker"` ignores it and moves ranks by the
   * ranker formula, balancing on the effective rating instead of the open one.
   */
  rating_mode: MixRatingMode;
  /** Per game (discipline code): the hero ban preset a new mix of that game starts with; an absent game, none. */
  hero_ban_presets: Record<string, string>;
  /** Per game (discipline code): how a new mix of that game forms its teams, and the draft's pick clock; absent = balancer, 30 s. */
  formation_defaults: Record<string, { team_formation: "balance" | "draft"; draft_pick_seconds: number }>;
  /**
   * Deadlock 6v6 lane balancing: `null` is the defaults (enabled, `DEFAULT_LANE_RULE`'s weights). Other games and
   * team sizes ignore it.
   */
  mix_rules: { lane_matchup: { enabled: boolean; weight: number; cohesion_weight: number } } | null;
};

/** The two ways a host's rank book reacts to a recorded match. */
export type MixRatingMode = "points" | "ranker";

export type MixBalancerPreferencesRead = MixBalancerPreferences;

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
