import { describe, expect, mock, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import type { DraftPlayer, DraftTeam } from "@/types/draft.types";

mock.module("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string, values?: Record<string, unknown>) =>
    values ? `${key}:${JSON.stringify(values)}` : key
}));

// Dynamic, not static: `mock.module` only applies to modules imported after it
// runs, and both components call `useTranslations` at render time.
const { PlayerPool } = await import("./PlayerPool");
const { DraftClockRing } = await import("./DraftClockRing");

const player = {
  id: 7,
  registration_id: 70,
  battle_tag: "Ana#1234",
  status: "available",
  primary_role: "support",
  sub_role: null,
  is_flex: false,
  is_captain: false,
  effective_rank: 3000,
  secondary_roles: ["damage"],
  role_ranks: { support: 3000, damage: 2800 },
  role_sources: {},
  drafted_by_team_id: null,
  notes: null
} as unknown as DraftPlayer;

const team: DraftTeam = {
  id: 3,
  session_id: 1,
  captain_user_id: null,
  captain_auth_user_id: null,
  name: "Team Three",
  draft_position: 1,
  exported_team_id: null
};

const POOL_COUNTS = { available: 1, shortlist: 0, drafted: 0 };

function renderPool(
  overrides: Partial<Parameters<typeof PlayerPool>[0]> = {},
  headingId = "player-pool-mobile-heading"
) {
  return renderToStaticMarkup(
    <PlayerPool
      players={[player]}
      totalPlayers={1}
      roleCounts={{ tank: 0, damage: 1, support: 1 }}
      poolCounts={POOL_COUNTS}
      pool="available"
      selection={null}
      shortlist={new Set<number>()}
      role="all"
      sort="rank"
      query=""
      options={null}
      safetyRequired={false}
      teams={[team]}
      onSelect={() => {}}
      onOpenProfile={() => {}}
      onToggleShortlist={() => {}}
      onFiltersChange={() => {}}
      onResetFilters={() => {}}
      divisionGrid={{ tiers: [] }}
      headingId={headingId}
      {...overrides}
    />
  );
}

describe("draft accessibility contracts", () => {
  test("every role a player may be picked on is its own named button", () => {
    const html = renderPool();

    expect(html).not.toContain('role="button"');
    // Primary first, and each button names the role it would spend the player on.
    expect(html).toContain(
      'aria-label="pickAs:{&quot;player&quot;:&quot;Ana#1234&quot;,&quot;role&quot;:&quot;roles.support&quot;}"'
    );
    expect(html).toContain(
      'aria-label="pickAs:{&quot;player&quot;:&quot;Ana#1234&quot;,&quot;role&quot;:&quot;roles.damage&quot;}"'
    );
    // The role's OWN rank, not the player's effective one.
    expect(html).toContain("2800");
    // The name opens the profile; it is not the pick target.
    expect(html).toContain(
      'aria-label="openProfile:{&quot;player&quot;:&quot;Ana#1234&quot;}"'
    );
  });

  test("a blocked role stays reachable and says why", () => {
    const html = renderPool({
      safetyRequired: true,
      options: {
        pick_id: 1,
        pick_version: 2,
        draft_team_id: 3,
        options: [
          {
            player_id: 7,
            role: "support",
            is_safe: false,
            reason_code: "role_shortage",
            unmatched_slots: [],
            blocking_player_ids: [],
            suggestion_score: null
          }
        ]
      }
    });

    // aria-disabled, not `disabled`: the reason has to stay readable, and a
    // disabled button is skipped by every screen reader's form controls list.
    expect(html).toContain('aria-disabled="true"');
    expect(html).toContain('title="optionReason.role_shortage"');
  });

  test("a spectator pool carries no pick buttons at all", () => {
    const html = renderPool({ onSelect: undefined, onToggleShortlist: undefined });

    expect(html).not.toContain("pickAs:");
    expect(html).not.toContain("addShortlist");
    // Still readable: the roles and their ranks are public information.
    expect(html).toContain("2800");
    expect(html).toContain("openProfile:");
  });

  test("the drafted tab names the team instead of offering roles", () => {
    const html = renderPool({
      pool: "drafted",
      players: [{ ...player, status: "picked", drafted_by_team_id: 3 } as DraftPlayer],
      poolCounts: { available: 0, shortlist: 0, drafted: 1 }
    });

    expect(html).toContain("Team Three");
    expect(html).not.toContain("pickAs:");
  });

  test("each mounted pool owns a unique heading id", () => {
    // The mobile and desktop trees are both mounted, so a hardcoded id would
    // make aria-labelledby resolve to the wrong section.
    const mobile = renderPool({}, "player-pool-mobile-heading");
    const desktop = renderPool({}, "player-pool-desktop-heading");

    expect(mobile).toContain('id="player-pool-mobile-heading"');
    expect(desktop).toContain('id="player-pool-desktop-heading"');
    expect(mobile).not.toContain("player-pool-desktop-heading");
  });

  test("the pick clock exposes a named timer plus a polite region", () => {
    const html = renderToStaticMarkup(
      <DraftClockRing expiresAt={null} paused={false} totalSeconds={60} accent="live" />
    );

    expect(html).toContain('role="timer"');
    expect(html).toContain('aria-label="draft.clock.idle"');
    expect(html).toContain('aria-live="polite"');
  });
});
