import { describe, expect, test, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { RosterShape } from "@/lib/roster/shape";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { DraftFormatSettings, DraftSession } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { DraftCaptainsStep } from "./DraftCaptainsStep";
import { DraftConfigStep } from "./DraftConfigStep";
import { DraftHistoryPanel } from "./DraftHistoryPanel";
import { DraftFormatFields } from "./DraftFormatFields";
import { DraftOrderStep } from "./DraftOrderStep";
import type { DraftSetupConfig } from "./setup-types";

const SESSIONS = vi.hoisted(
  () =>
    [
      { id: 12, status: "live", format: "snake", rounds: 4, created_at: "2026-02-01T10:00:00Z" },
      {
        id: 11,
        status: "cancelled",
        format: "linear",
        rounds: 4,
        created_at: "2026-01-30T10:00:00Z"
      }
    ] as unknown as DraftSession[]
);

// Translations resolve to `key:{values}` so an assertion names the message key
// instead of a copy string, and the formatter is pinned so the row is stable.
vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string, values?: Record<string, unknown>) =>
    values ? `${key}:${JSON.stringify(values)}` : key
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: () => "1 Feb 2026, 10:00" })
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: SESSIONS, isLoading: false, isError: false, refetch: () => {} }),
  useMutation: () => ({ mutate: () => {}, isPending: false }),
  useQueryClient: () => ({ invalidateQueries: async () => {} })
}));

const SHAPE: RosterShape = {
  slots: { flex: 5 },
  team_size: 5,
  flex_slots: 5,
  has_role_slots: false,
  draft_rounds: 4,
  source: "tournament"
};

const CONFIG: DraftSetupConfig = {
  teamCount: 2,
  pickTimeSeconds: 45,
  overtimeSeconds: 0,
  autopickStrategy: "best_fit",
  allowAdminOverride: true
};

const SNAKE: DraftFormatSettings = {
  format: "snake",
  round_rules: [],
  avg_tie_seed_reverse: false
};

function registration(id: number, roles: string[], rank: number | null): AdminRegistration {
  return {
    id,
    battle_tag: `Player${id}#1000`,
    display_name: null,
    user_id: id,
    deleted_at: null,
    balancer_status_meta: { excludes_from_balancer: false },
    roles: roles.map((role, index) => ({
      role,
      is_active: true,
      is_primary: index === 0,
      priority: index,
      rank_value: rank
    }))
  } as unknown as AdminRegistration;
}

const POOL = [
  registration(1, ["tank", "damage", "support"], null),
  registration(2, ["support", "tank"], 2600),
  registration(3, ["damage"], 3800)
];

// Deliberately NOT the OW ladder: 2600 and 3800 sit in Diamond/Grandmaster
// there, so a step that quietly fell back to the global grid (or the workspace
// default) would resolve different tiers than the two named here.
const TOURNAMENT_GRID: DivisionGrid = {
  tiers: [
    { number: 1, name: "Iron League", rank_min: 0, rank_max: 2999, icon_url: "/iron.png" },
    { number: 2, name: "Steel League", rank_min: 3000, rank_max: null, icon_url: "/steel.png" }
  ]
};

describe("draft config step", () => {
  const html = renderToStaticMarkup(
    <DraftConfigStep
      value={CONFIG}
      onChange={() => {}}
      rosterShape={SHAPE}
      format={SNAKE}
      tournamentId={5}
    />
  );

  test("renders the pick-time presets as one segmented control, not four loose buttons", () => {
    // Pick time and overtime are the two `role=group` widgets here; the format
    // is the tournament's and only named, never edited.
    expect(html.match(/<div[^>]*role="group"[^>]*aria-labelledby[^>]*>/g) ?? []).toHaveLength(2);
    for (const seconds of [30, 45, 60, 90]) {
      expect(html).toContain(`>${seconds}s</button>`);
    }
    // One pressed preset per group (45s pick time, overtime off), and the
    // free-form fields are labelled as custom overrides, not extra presets.
    expect(html.match(/aria-pressed="true"/g) ?? []).toHaveLength(2);
    expect(html).toContain('for="draft-pick-time"');
    expect(html).toContain("customPickTime");
  });

  test("offers overtime presets with an off option and a custom field", () => {
    expect(html).toContain("overtime");
    expect(html).toContain(">overtimeOff</button>");
    for (const seconds of [15, 30, 60]) {
      expect(html).toContain(`>${seconds}s</button>`);
    }
    expect(html).toContain('for="draft-overtime"');
    expect(html).toContain('id="draft-overtime"');
    // The main clock → overtime → autopick sequence is explained, not implied.
    expect(html).toContain("overtimeHint");
  });

  test("shows the roster slots as icons instead of role words", () => {
    // A flex-only shape renders the flex glyph plus its screen-reader label; the
    // visible text is the count, never "5 Flex".
    expect(html).toContain("<svg");
    expect(html).toContain("roles.flex");
    expect(html).not.toContain("5 roles.flex");
  });

  test("names the tournament's format read-only and links to where it is set", () => {
    expect(html).toContain("formats.snake.title");
    expect(html).not.toContain('role="radiogroup"');
    expect(html).toContain('href="/admin/tournaments/5/settings/draft"');
  });
});

describe("draft format fields", () => {
  const render = (value: DraftFormatSettings) =>
    renderToStaticMarkup(<DraftFormatFields value={value} onChange={() => {}} rounds={4} />);

  test("labels every custom round rule with its round", () => {
    const custom = render({ format: "custom", round_rules: [], avg_tie_seed_reverse: false });
    // Every rule select is bound to a visible "Round N" label, so which round a
    // rule applies to never depends on inferring the grid flow.
    for (const round of [1, 2, 3, 4]) {
      expect(custom).toContain(`for="draft-round-rule-${round}"`);
      expect(custom).toContain(`id="draft-round-rule-${round}"`);
      expect(custom).toContain(`roundNumber:{&quot;round&quot;:${round}}`);
    }
    expect(custom).toContain("roundRulesHint");
    // Snake never shows them at all.
    expect(render(SNAKE)).not.toContain("roundRules");
  });

  test("offers the reversed-seed tie-break only when a round ranks by team average", () => {
    const custom = (round_rules: string[]) =>
      render({ format: "custom", round_rules, avg_tie_seed_reverse: false });

    expect(custom(["linear", "team_avg_desc", "linear", "linear"])).toContain(
      'id="draft-avg-tie-seed"'
    );
    expect(custom(["linear", "strongest_first", "reverse", "linear"])).not.toContain(
      "draft-avg-tie-seed"
    );
  });
});

describe("draft captains step", () => {
  const ROLE_SHAPE = { slots: { tank: 1, damage: 2, support: 2 }, has_role_slots: true };
  const html = renderToStaticMarkup(
    <DraftCaptainsStep
      pool={POOL}
      teamCount={2}
      value={{ ids: [], teamNames: {}, roles: {}, order: "weakest_first", randomSeed: 1 }}
      onChange={() => {}}
      divisionGrid={TOURNAMENT_GRID}
      rosterShape={ROLE_SHAPE}
    />
  );

  test("filters roles through counted chips instead of a single-value dropdown", () => {
    // All + three roles + Selected, every one a real pressed-state button.
    expect(html.match(/<button[^>]*aria-pressed="(true|false)"[^>]*>/g) ?? []).toHaveLength(5);
    expect(html).toContain('aria-label="captainPoolFilters"');
    expect(html).toContain("captainFilters.all");
    expect(html).toContain("captainFilters.selected");
    // Nothing is selected yet, so the Selected chip counts 0 of 2 teams.
    expect(html).toContain("0/2");
    // The removed dropdown's "all roles" option must be gone: an empty role
    // selection now means every role.
    expect(html).not.toContain("allRoles");
  });

  test("offers a rank sort and a labelled search field", () => {
    // Radix renders its options in a portal, so SSR only exposes the trigger.
    expect(html).toContain('aria-label="captainSort"');
    expect(html).toContain('type="search"');
    expect(html).toContain("searchCaptains");
  });

  test("renders each candidate's roles as glyphs and the rank as a division icon", () => {
    // Roles used to be text badges; they are icons now, announced by role name.
    expect(html).toContain('aria-label="roles.tank"');
    expect(html).toContain('aria-label="roles.damage"');
    expect(html).toContain('aria-label="roles.support"');
    // Ranked candidates carry a division image; the unranked one still shows a dash.
    expect(html).toContain("<img");
    expect(html).toContain("3800");
    expect(html).toContain("—");
  });

  test("resolves divisions on the tournament's grid, not the global OW ladder", () => {
    // `alt` comes from the tier NAME the grid resolves the rank to, so these two
    // names appear only if the passed grid — not the OW ladder underneath
    // `useDivisionGrid` — did the lookup.
    expect(html).toContain('alt="Iron League"');
    expect(html).toContain('alt="Steel League"');
    expect(html).not.toContain('alt="Diamond');
    expect(html).not.toContain('alt="Grandmaster');
  });

  test("sorts the pool by rank descending by default", () => {
    expect(html.indexOf("Player3#1000")).toBeLessThan(html.indexOf("Player2#1000"));
    expect(html.indexOf("Player2#1000")).toBeLessThan(html.indexOf("Player1#1000"));
  });

  test("lets the organizer choose the role of a captain who plays more than one", () => {
    const selected = renderToStaticMarkup(
      <DraftCaptainsStep
        pool={POOL}
        teamCount={2}
        value={{ ids: [2, 3], teamNames: {}, roles: {}, order: "weakest_first", randomSeed: 1 }}
        onChange={() => {}}
        divisionGrid={TOURNAMENT_GRID}
        rosterShape={ROLE_SHAPE}
      />
    );
    // Support + tank: a choice. Damage only: nothing to pick.
    expect(selected).toContain("captainRoleFor:{&quot;name&quot;:&quot;Player2#1000&quot;}");
    expect(selected).not.toContain("captainRoleFor:{&quot;name&quot;:&quot;Player3#1000&quot;}");
  });
});

describe("draft order step", () => {
  test("keeps a computed order draggable so its seeds can be overridden", () => {
    const html = renderToStaticMarkup(
      <DraftOrderStep
        value={{ ids: [2, 3], teamNames: {}, roles: {}, order: "weakest_first", randomSeed: 1 }}
        onChange={() => {}}
        pool={POOL}
        rounds={4}
        format="snake"
        roundRules={[]}
        rosterShape={{ slots: { tank: 1, damage: 2, support: 2 }, has_role_slots: true }}
      />
    );
    // Weakest first: 2600 before 3800, each with a drag handle.
    expect(html.indexOf("Player2#1000")).toBeLessThan(html.indexOf("Player3#1000"));
    expect(html).toContain("moveCaptain:{&quot;name&quot;:&quot;Player2#1000&quot;}");
    expect(html).toContain("dragToOverrideSeeds");
  });
});

describe("draft history panel", () => {
  // react-dom/server escapes quotes in text nodes, so the mocked translation's
  // JSON payload lands as &quot; in the markup.
  const session = (id: number) => `sessionNumber:{&quot;id&quot;:${id}}`;

  const html = renderToStaticMarkup(
    <DraftHistoryPanel tournamentId={5} onSessionDeleted={() => {}} />
  );

  test("lists every session with its status", () => {
    expect(html).toContain("history.title");
    expect(html).toContain(session(12));
    expect(html).toContain(session(11));
    expect(html).toContain("statuses.live");
    expect(html).toContain("statuses.cancelled");
  });

  test("blocks deleting an in-flight draft and allows it for a terminal one", () => {
    const live = html.slice(html.indexOf(session(12)), html.indexOf(session(11)));
    const cancelled = html.slice(html.indexOf(session(11)));

    expect(live).toContain("history.cancelFirst");
    expect(live).toContain('disabled=""');
    expect(cancelled).toContain("history.delete");
    expect(cancelled).not.toContain("history.cancelFirst");
    expect(cancelled).not.toContain('disabled=""');
  });
});
