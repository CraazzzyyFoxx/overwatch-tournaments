import { describe, expect, test, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { RosterShape } from "@/lib/roster/shape";
import { DEADLOCK_METADATA, OW_METADATA } from "@/test/discipline-metadata";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { DraftFeasibility, DraftFormatSettings, DraftSession } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { DraftCaptainsStep } from "./DraftCaptainsStep";
import { DraftConfigStep } from "./DraftConfigStep";
import { DraftHistoryPanel } from "./DraftHistoryPanel";
import { DraftFormatFields } from "./DraftFormatFields";
import { DraftOrderStep } from "./DraftOrderStep";
import { DraftPoolStep } from "./DraftPoolStep";
import { DraftReadyStep } from "./DraftReadyStep";
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
  useTranslations: () =>
    Object.assign(
      (key: string, values?: Record<string, unknown>) => (values ? `${key}:${JSON.stringify(values)}` : key),
      { has: () => false }
    )
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: () => "1 Feb 2026, 10:00" })
}));

vi.mock("@tanstack/react-query", () => ({
  // The sessions read; the rank crests' workspace read (`["admin-workspace", id]`) has nothing loaded.
  useQuery: ({ queryKey }: { queryKey: readonly unknown[] }) => ({
    data: queryKey[0] === "admin-workspace" ? undefined : SESSIONS,
    isLoading: false,
    isError: false,
    refetch: () => {}
  }),
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
    primary_handle: `Player${id}#1000`,
    display_name: null,
    user_id: id,
    deleted_at: null,
    balancer_status_meta: { excludes_from_balancer: false },
    roles: roles.map((role, index) => ({
      role: { dimension: "player_role", role },
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
      ontology={OW_METADATA}
      format={SNAKE}
      tournamentId={5}
    />
  );

  test("renders the pick-time presets as one segmented control, not four loose buttons", () => {
    // Pick time and overtime are the two labelled radiogroups here; the format
    // is the tournament's and only named, never edited.
    expect(html.match(/<div(?=[^>]*role="radiogroup")(?=[^>]*aria-labelledby)[^>]*>/g) ?? []).toHaveLength(2);
    for (const seconds of [30, 45, 60, 90]) {
      expect(html).toContain(`>${seconds}s</button>`);
    }
    // One checked preset per group (45s pick time, overtime off), and the
    // free-form fields are labelled as custom overrides, not extra presets.
    expect(html.match(/role="radio" aria-checked="true"/g) ?? []).toHaveLength(2);
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
    expect(html).toContain(">flex<");
    expect(html).not.toContain("5 flex");
  });

  test("names the tournament's format read-only and links to where it is set", () => {
    expect(html).toContain("formats.snake.title");
    // The other formats are never offered here: the wizard does not edit it.
    expect(html).not.toContain("formats.linear.title");
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
      ontology={OW_METADATA}
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
    expect(html).toContain('aria-label="Tank"');
    expect(html).toContain('aria-label="Damage"');
    expect(html).toContain('aria-label="Support"');
    // Ranked candidates carry a division image; the unranked one shows nothing,
    // never a dash placeholder.
    expect(html).toContain("<img");
    expect(html).toContain("3800");
    expect(html).not.toContain("—");
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

  test("offers one actions menu per session instead of a row of buttons", () => {
    // The menu content (and whether Delete is offered) is portalled on open;
    // the behavior suite opens it. Statically, each row has exactly one trigger.
    expect(html.match(/aria-haspopup="menu"/g) ?? []).toHaveLength(2);
    expect(html).not.toContain("history.delete");
  });
});

describe("draft ready step", () => {
  const readySession = { id: 3, roster_shape: SHAPE, rounds: 4, pick_time_seconds: 45 } as unknown as DraftSession;
  const render = (feasibility: Pick<DraftFeasibility, "is_feasible"> | null, failed = false) =>
    renderToStaticMarkup(
      <DraftReadyStep
        tournamentId={5}
        session={readySession}
        feasibility={feasibility as DraftFeasibility | null}
        feasibilityFailed={failed}
        onRetryFeasibility={() => {}}
        pending={false}
        onStart={() => {}}
        onReseed={() => {}}
      />
    );

  test("keeps Start visible and disabled until feasibility says the draft can start", () => {
    // Start is the only control here that can be disabled while nothing is pending.
    for (const [feasibility, disabled] of [
      [null, true],
      [{ is_feasible: false }, true],
      [{ is_feasible: true }, false]
    ] as const) {
      const html = render(feasibility);
      expect(html).toContain("startDraft");
      expect(html.includes('disabled=""')).toBe(disabled);
    }
    expect(render(null)).toContain("checkingFeasibility");
    expect(render(null)).not.toContain("notReadyToStart");
  });

  test("names the failed feasibility check as Start's reason and offers a retry", () => {
    const html = render(null, true);
    expect(html).not.toContain("checkingFeasibility");
    expect(html).toContain("retry");
    expect(html.includes('disabled=""')).toBe(true);
    const describedBy = /aria-describedby="([^"]+)"/.exec(html)?.[1];
    const reasonAt = html.indexOf(`id="${describedBy}"`);
    expect(reasonAt).toBeGreaterThan(-1);
    expect(html.slice(reasonAt, html.indexOf("</p>", reasonAt))).toContain("loadFailed");
  });
});

describe("draft pool step", () => {
  /** One role short, with the server's deficit for it: the strip and both lines say who is missing. */
  const render = (ontology: typeof OW_METADATA, role: string) =>
    renderToStaticMarkup(
      <DraftPoolStep
        readiness={{
          requiredPlayers: 12,
          actualPlayers: 10,
          missingRanks: 0,
          missingAccounts: 0,
          excludedPlayers: 0,
          roleCoverage: { [role]: 10 },
          blockers: [`role_shortage:${role}`]
        }}
        feasibility={{ is_feasible: false, slot_deficits: [{ slot_code: role, unmatched_slots: 2 }] } as unknown as DraftFeasibility}
        loading={false}
        failed={false}
        onRetry={() => {}}
        teamCount={2}
        maxTeamCount={1}
        pinned
        onTeamCountChange={() => {}}
        ontology={ontology}
      />
    );

  test("names the role short of players in a game with roles", () => {
    const html = render(OW_METADATA, "tank");
    expect(html).toContain("roleCoverage");
    expect(html).toContain('blockers.role_shortage:{&quot;role&quot;:&quot;Tank&quot;}');
    expect(html).toContain('roleDeficit:{&quot;role&quot;:&quot;Tank&quot;,&quot;count&quot;:2}');
  });

  test("counts seats, never the role, in a one-role game", () => {
    const html = render(DEADLOCK_METADATA, "agent");
    expect(html).not.toMatch(/agent/i);
    expect(html).not.toContain("roleCoverage");
    expect(html).toContain("blockers.seat_shortage");
    expect(html).toContain('seatDeficit:{&quot;count&quot;:2}');
  });
});
