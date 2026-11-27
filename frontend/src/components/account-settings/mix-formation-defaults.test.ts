import { describe, expect, it } from "vitest";

import { draftOf, preferencesPayload } from "./mix-balancer-prefs";

describe("per-game formation defaults", () => {
  const stored = {
    mix_comfort_tilt: null,
    role_settings: null,
    max_result_variants: null,
    open_slot_settings: null,
    points_per_win: null,
    rating_mode: "points" as const,
    hero_ban_presets: {},
    formation_defaults: { deadlock: { team_formation: "draft" as const, draft_pick_seconds: 45 } },
    mix_rules: null,
  };

  it("travel from the stored row through the draft back to the payload", () => {
    expect(preferencesPayload(draftOf(stored)).formation_defaults).toEqual({
      deadlock: { team_formation: "draft", draft_pick_seconds: 45 },
    });
    expect(preferencesPayload(draftOf(undefined)).formation_defaults).toEqual({});
  });

  it("serialize the same whichever order the games were set in", () => {
    const first = { team_formation: "draft" as const, draft_pick_seconds: 30 };
    const second = { team_formation: "balance" as const, draft_pick_seconds: 60 };
    const row = (formation_defaults: typeof stored.formation_defaults) =>
      JSON.stringify(preferencesPayload(draftOf({ ...stored, formation_defaults })));

    expect(row({ overwatch: first, deadlock: second } as never)).toBe(row({ deadlock: second, overwatch: first } as never));
    // Nor the order a game's own fields come back in.
    expect(row({ deadlock: { draft_pick_seconds: 60, team_formation: "balance" } } as never)).toBe(
      row({ deadlock: second } as never),
    );
  });
});
