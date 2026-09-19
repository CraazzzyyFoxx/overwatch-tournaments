import { describe, expect, mock, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import type { DraftPlayer } from "@/types/draft.types";

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
  secondary_roles: [],
  role_ranks: {},
  role_sources: {},
  notes: null
} as unknown as DraftPlayer;

function renderPool(headingId: string) {
  return renderToStaticMarkup(
    <PlayerPool
      players={[player]}
      totalPlayers={1}
      roleCounts={{ tank: 0, damage: 0, support: 1 }}
      selectedPlayerId={null}
      shortlist={new Set<number>()}
      role="all"
      sort="rank"
      query=""
      options={null}
      safetyRequired={false}
      onSelect={() => {}}
      onToggleShortlist={() => {}}
      onFiltersChange={() => {}}
      onResetFilters={() => {}}
      divisionGrid={{ tiers: [] }}
      headingId={headingId}
    />
  );
}

describe("draft accessibility contracts", () => {
  test("a pool row selects through a real button, never a div[role=button]", () => {
    const html = renderPool("player-pool-mobile-heading");

    expect(html).not.toContain('role="button"');
    expect(html).toContain('aria-label="selectPlayer:{&quot;player&quot;:&quot;Ana#1234&quot;}"');
    // The select button is childless, so the profile link stays a sibling and
    // never gets absorbed into the button's accessible name.
    expect(html).toMatch(/aria-label="selectPlayer:[^"]*"[^>]*><\/button>/);
  });

  test("each mounted pool owns a unique heading id", () => {
    // The mobile and desktop trees are both mounted, so a hardcoded id would
    // make aria-labelledby resolve to the wrong section.
    const mobile = renderPool("player-pool-mobile-heading");
    const desktop = renderPool("player-pool-desktop-heading");

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
