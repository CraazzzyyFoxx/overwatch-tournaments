import { describe, expect, it } from "vitest";

import { draftOf, preferencesPayload } from "./mix-balancer-prefs";

describe("per-game ban defaults", () => {
  const stored = {
    mix_comfort_tilt: null,
    role_settings: null,
    max_result_variants: null,
    open_slot_settings: null,
    points_per_win: null,
    rating_mode: "points" as const,
    hero_ban_presets: { deadlock: "deadlock_hero_bans" },
    formation_defaults: {},
    mix_rules: null,
  };

  it("travel from the stored row through the draft back to the payload", () => {
    expect(preferencesPayload(draftOf(stored)).hero_ban_presets).toEqual({ deadlock: "deadlock_hero_bans" });
    expect(preferencesPayload(draftOf(undefined)).hero_ban_presets).toEqual({});
  });

  // The panel compares serialized rows to decide whether to save, and the server's jsonb answers the games in its
  // own key order: the order a host set them in must not read as an unsaved change.
  it("serialize the same whichever order the games were set in", () => {
    const row = (hero_ban_presets: Record<string, string>) =>
      JSON.stringify(preferencesPayload(draftOf({ ...stored, hero_ban_presets })));

    expect(row({ overwatch: "hero_classic", deadlock: "deadlock_hero_bans" })).toBe(
      row({ deadlock: "deadlock_hero_bans", overwatch: "hero_classic" }),
    );
  });
});
