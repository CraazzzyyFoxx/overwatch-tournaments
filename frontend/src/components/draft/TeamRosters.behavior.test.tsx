import { describe, expect, mock, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import type { RosterShape } from "@/lib/roster-shape";
import type { DraftPick, DraftPlayer, DraftTeam } from "@/types/draft.types";

mock.module("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string, values?: Record<string, unknown>) =>
    values ? `${key}:${JSON.stringify(values)}` : key
}));

// Dynamic, not static: `mock.module` only applies to modules imported after it
// runs, and the component calls `useTranslations` at render time.
const { TeamRosters } = await import("./TeamRosters");

const ROLE_SHAPE: RosterShape = {
  slots: { tank: 1, damage: 2, support: 2 },
  team_size: 5,
  flex_slots: 0,
  has_role_slots: true,
  draft_rounds: 4,
  source: "tournament"
};
const FLEX_SHAPE: RosterShape = {
  slots: { flex: 5 },
  team_size: 5,
  flex_slots: 5,
  has_role_slots: false,
  draft_rounds: 4,
  source: "tournament"
};

const team: DraftTeam = {
  id: 1,
  session_id: 1,
  captain_user_id: null,
  captain_auth_user_id: null,
  name: "Team",
  draft_position: 1,
  exported_team_id: null
};

// Two tiers so a rank resolves to a division: with an empty grid every rank
// resolves to null and the row renders an em-dash instead of a title carrying
// the number the assertions read.
const GRID = {
  tiers: [
    { slug: "high", number: 9, name: "High", sort_order: 0, rank_min: 4000, rank_max: 4999, icon_url: "/high.png" },
    { slug: "low", number: 4, name: "Low", sort_order: 1, rank_min: 2000, rank_max: 2999, icon_url: "/low.png" }
  ]
};

// Drafted on support at 2800, but their best role is damage at 4000 — the two ranks
// the shape has to choose between. `effective_rank` is what the roster engine
// resolved for THIS draft.
const drafted: DraftPlayer = {
  id: 7,
  session_id: 1,
  registration_id: 70,
  user_id: null,
  battle_tag: "Ana#1234",
  primary_role: "support",
  sub_role: null,
  is_flex: false,
  effective_rank: 4000,
  status: "picked",
  is_captain: false,
  drafted_by_team_id: 1,
  secondary_roles: ["damage"],
  role_ranks: { support: 2800, damage: 4000 },
  role_sources: { support: "registration", damage: "registration" },
  role_top_heroes: {},
  notes: null,
  custom_fields: [],
  version: 1
};

const pick = {
  id: 9,
  session_id: 1,
  draft_team_id: 1,
  picked_player_id: 7,
  target_role: "support",
  target_rank_value: 2800,
  status: "completed"
} as unknown as DraftPick;

function render(
  shape: RosterShape,
  variant: "grid" | "column",
  players: DraftPlayer[] = [drafted],
  picks: DraftPick[] = [pick]
) {
  return renderToStaticMarkup(
    <TeamRosters
      teams={[team]}
      players={players}
      picks={picks}
      shape={shape}
      variant={variant}
      divisionGrid={GRID}
    />
  );
}

describe.each(["grid", "column"] as const)("team roster rows (%s)", (variant) => {
  test("a role slot shows the drafted role and that role's rank", () => {
    const html = render(ROLE_SHAPE, variant);

    expect(html).toContain('title="roles.support"');
    expect(html).not.toContain("roles.flex");
    expect(html).toContain("2800 SR");
    expect(html).not.toContain("4000 SR");
  });

  test("an all-flex roster shows the flex slot and the player's best rank", () => {
    // The shape assigned nobody a role, so a role icon would state an
    // assignment that was never made and the drafted role's rank would
    // understate a player whose best role is stronger.
    const html = render(FLEX_SHAPE, variant);

    expect(html).toContain('title="roles.flex"');
    expect(html).not.toContain('title="roles.support"');
    expect(html).toContain("4000 SR");
    expect(html).not.toContain("2800 SR");
  });

  test("a player left without a playable role gets no stand-in role", () => {
    // An organizer can strip every rank mid-draft. Falling back to a default
    // role would put a tank icon on a player nobody can field.
    // No pick froze a role for them either, so nothing can stand in.
    const html = render(
      ROLE_SHAPE,
      variant,
      [{ ...drafted, primary_role: null, secondary_roles: [], role_ranks: {} }],
      []
    );
    // The row's own slot label is `noRole`, so no role was substituted — the
    // shape's slot counters above still name every role, which is why the
    // assertion targets the row label rather than the whole document.
    expect(html).toContain('title="noRole"');
    expect(html).not.toContain("SR");
  });
});
