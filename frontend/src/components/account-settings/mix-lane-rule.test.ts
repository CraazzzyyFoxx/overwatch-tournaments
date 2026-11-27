import { describe, expect, it } from "vitest";

import { DEFAULT_LANE_RULE, draftOf, preferencesPayload } from "./mix-balancer-prefs";

describe("lane matchup rule preferences", () => {
  const stored = {
    mix_comfort_tilt: null,
    role_settings: null,
    max_result_variants: null,
    open_slot_settings: null,
    points_per_win: null,
    rating_mode: "points" as const,
    hero_ban_presets: {},
    formation_defaults: {},
    mix_rules: null,
  };

  it("sends null while all three knobs sit at their defaults", () => {
    expect(draftOf(undefined).laneRule).toEqual(DEFAULT_LANE_RULE);
    expect(preferencesPayload(draftOf(stored)).mix_rules).toBeNull();
    expect(
      preferencesPayload(
        draftOf({ ...stored, mix_rules: { lane_matchup: { enabled: true, weight: 0.5, cohesion_weight: 0.25 } } }),
      ).mix_rules,
    ).toBeNull();
  });

  it("sends the whole rule once any knob moves, and round-trips it", () => {
    const rules = { lane_matchup: { enabled: false, weight: 2, cohesion_weight: 0.25 } };
    expect(preferencesPayload(draftOf({ ...stored, mix_rules: rules })).mix_rules).toEqual(rules);

    const draft = { ...draftOf(stored), laneRule: { ...DEFAULT_LANE_RULE, cohesion: 1 } };
    expect(preferencesPayload(draft).mix_rules).toEqual({
      lane_matchup: { enabled: true, weight: 0.5, cohesion_weight: 1 },
    });
  });

  it("clamps a stored weight to the server's range", () => {
    const rules = { lane_matchup: { enabled: true, weight: 99, cohesion_weight: -1 } };
    expect(draftOf({ ...stored, mix_rules: rules }).laneRule).toEqual({ enabled: true, weight: 10, cohesion: 0 });
  });
});
