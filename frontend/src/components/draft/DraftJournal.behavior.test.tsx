import { describe, expect, test, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { DEADLOCK_METADATA, OW_METADATA } from "@/test/discipline-metadata";
import type { DraftBoard, DraftJournalEntry } from "@/types/draft.types";

import { DraftJournal } from "./DraftJournal";

// Message keys, not copy: the assertions are about which facts a sentence carries.
vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () =>
    Object.assign(
      (key: string, values?: Record<string, unknown>) => (values ? `${key}:${JSON.stringify(values)}` : key),
      { has: () => false }
    )
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: (value: Date) => value.toISOString() })
}));

const board = {
  teams: [{ id: 1, name: "Team Rocket" }],
  players: [{ id: 7, identity: { provider: "steam", handle: "Ana#1234" }, display: { name: "Ana#1234", tag: null, canonical: null, snapshot: null } }]
} as unknown as DraftBoard;

function entry(id: number, action: DraftJournalEntry["action"], dimension: string, role: string): DraftJournalEntry {
  return {
    id,
    created_at: "2026-10-21T10:00:00Z",
    action,
    actor_auth_user_id: null,
    actor_name: null,
    reason: null,
    pick_no: 3,
    team_id: 1,
    player_id: 7,
    role: { dimension, role },
    seconds: null
  };
}

function render(ontology: typeof OW_METADATA, entries: DraftJournalEntry[]) {
  return renderToStaticMarkup(
    <DraftJournal
      id="journal"
      board={board}
      entries={entries}
      ontology={ontology}
      isLoading={false}
      isError={false}
      onRetry={() => {}}
    />
  );
}

describe("DraftJournal", () => {
  test("a one-role game's sentences name the pick and the player, never the role", () => {
    const html = render(DEADLOCK_METADATA, [
      entry(1, "pick_made", "agent", "agent"),
      entry(2, "player_role_added", "agent", "agent")
    ]);

    expect(html).toContain("Ana#1234");
    expect(html).toContain("Team Rocket");
    expect(html).not.toContain("Agent");
    expect(html).not.toContain("&quot;role&quot;");
  });

  test("a multi-role game's pick still names the role", () => {
    const html = render(OW_METADATA, [entry(1, "pick_made", "player_role", "support")]);

    expect(html).toContain("&quot;role&quot;:&quot;Support&quot;");
  });
});
