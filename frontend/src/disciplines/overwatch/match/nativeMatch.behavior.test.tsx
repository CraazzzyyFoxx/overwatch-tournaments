// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setTimeout as sleep } from "node:timers/promises";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MatchStats from "./MatchStats";
import SeriesStats from "./SeriesStats";
import KillFeedTimeline from "./KillFeedTimeline";
import type { DisciplineMetadata } from "@/types/discipline.types";
import type { Encounter, MatchWithStats } from "@/types/encounter.types";
import type { MatchEvent, MatchEvents } from "@/types/killfeed.types";
import messages from "@/i18n/messages/en.json";
import { LogStatsName } from "../stat-names";
import type { OwTeam } from "./view";

const { getMatchKillFeed } = vi.hoisted(() => ({ getMatchKillFeed: vi.fn() }));

// The series panel's contribution chart is lazy. Left lazy, recharts finished loading in
// whichever test ran next and billed that test its import time (seconds under a
// loaded runner). Every `dynamic()` here is that chart: resolve it up front
// (imported inside the factory because `vi.mock` is hoisted above static imports).
vi.mock("next/dynamic", async () => {
  const chart = await import("./ContributionChart");
  return { default: () => chart.default };
});
vi.mock("@/services/encounter.service", () => ({ default: { getMatchKillFeed } }));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ number: (value: number) => String(value) })
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | null = null;
// An ontology with no rated dimension: classes stay neutral, no glyphs.
const metadata = { dimensions: [], roles: [] } as unknown as DisciplineMetadata;

/** A duel of two participations whose source teams are gone (`tournament_team_id: null`); one observed member each. */
function match(
  sides: { id: number; name: string; eliminations: number }[],
  overrides: Partial<MatchWithStats> = {}
): MatchWithStats {
  return {
    id: 7,
    created_at: "1970-01-01T00:00:00Z",
    updated_at: null,
    played_at: null,
    workspace_id: 1,
    discipline: "overwatch",
    encounter_id: 1,
    encounter_game_id: null,
    map_id: 1,
    map_index: null,
    map: null,
    encounter: null,
    duration_s: null,
    log_name: null,
    raw_status: "missing",
    raw_available: false,
    participants: sides.map((side, index) => ({
      encounter_team_id: side.id,
      slot: index + 1,
      source_position: index,
      tournament_team_id: null,
      name: side.name,
      result: null,
      team_facts: { score: 2 - index }
    })),
    statistics: {
      members: sides.map((side) => ({
        encounter_team_id: side.id,
        workspace_member_id: side.id * 10,
        player_id: side.id * 10,
        // Side 102's player has no canonical name on the wire: its handle must stay unlinked.
        player_name: side.id === 102 ? null : `Canonical ${side.id}`,
        handle_snapshot: `Observed ${side.id}#1`,
        observed_role: null
      })),
      segments: [],
      facts: sides.flatMap((side, index) => [
        {
          encounter_team_id: side.id,
          workspace_member_id: side.id * 10,
          entity_id: null,
          segment: 0,
          stat_code: LogStatsName.Eliminations,
          value: side.eliminations
        },
        {
          encounter_team_id: side.id,
          workspace_member_id: side.id * 10,
          entity_id: null,
          segment: 0,
          stat_code: LogStatsName.ImpactRank,
          value: index + 1
        }
      ]),
      entities: []
    },
    ...overrides
  };
}

const historical = (): MatchWithStats =>
  match([
    { id: 101, name: "Archived A", eliminations: 12 },
    { id: 102, name: "Archived B", eliminations: 5 }
  ]);

function seats(...ids: number[]): Encounter {
  return { teams: ids.map((id) => ({ id })) } as unknown as Encounter;
}

function event(overrides: Partial<MatchEvent> = {}): MatchEvent {
  return {
    id: 1,
    segment: 1,
    t: 17,
    type: "kill",
    actor_member_id: null,
    actor_team_id: null,
    target_member_id: null,
    target_team_id: null,
    entity_id: null,
    related_entity_id: null,
    data: null,
    ...overrides
  };
}

const side = (id: number, name: string): OwTeam => ({
  id,
  slot: id,
  team_id: null,
  name,
  team: null,
  live: null,
  players: []
});

async function mount(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(node);
  });
  return container;
}

/** The scoreboard inside its query client, with an empty kill feed for the tabs that read one. */
async function mountStats(value: MatchWithStats) {
  getMatchKillFeed.mockResolvedValue({ match_id: value.id, discipline: "overwatch", events: [], entities: [] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return mount(
    <QueryClientProvider client={client}>
      <MatchStats match={value} metadata={metadata} />
    </QueryClientProvider>
  );
}

/** Radix tabs activate on mousedown; the panel that answers is the active one. */
async function openTab(container: HTMLElement, label: string) {
  const tab = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find(
    (button) => button.textContent === label
  )!;
  await act(async () => {
    tab.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
    tab.click();
  });
  for (let turn = 0; turn < 20 && container.querySelector('[role="tabpanel"][data-state="active"] [role="status"]'); turn++) {
    await act(async () => {
      await sleep(10);
    });
  }
  return container.querySelector<HTMLElement>('[role="tabpanel"][data-state="active"]')!;
}

async function timeline(events: MatchEvent[], home = side(1, "Home"), away = side(2, "Away")) {
  const feed: MatchEvents = { match_id: 7, discipline: "overwatch", events, entities: [] };
  getMatchKillFeed.mockResolvedValue(feed);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const container = await mount(
    <QueryClientProvider client={client}>
      <KillFeedTimeline matchId={7} members={[]} home={home} away={away} round={0} focus={null} />
    </QueryClientProvider>
  );
  // The query settles on a timer outside React: give it turns until the loading skeleton is gone.
  for (let turn = 0; turn < 20 && container.querySelector('[role="status"]'); turn++) {
    await act(async () => {
      await sleep(10);
    });
  }
  return container;
}

const timestamps = (container: HTMLElement): string[] =>
  Array.from(container.querySelectorAll("span"))
    .map((element) => element.textContent ?? "")
    .filter((text) => /^\d+:\d{2}$/.test(text));

afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  root = null;
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

// happy-dom lays nothing out, so recharts' ResponsiveContainer measures 0×0
// and warns that the chart is invisible. Give its box a browser-like size.
const measure = HTMLElement.prototype.getBoundingClientRect;
beforeEach(() => {
  getMatchKillFeed.mockReset();
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    return this.classList.contains("recharts-responsive-container")
      ? new DOMRect(0, 0, 600, 300)
      : measure.call(this);
  });
});

describe("historical observed participations", () => {
  it("keeps both participations' observations and snapshot names without a source team", () => {
    const container = document.createElement("div");
    container.innerHTML = renderToStaticMarkup(
      <MatchStats match={historical()} metadata={metadata} />
    );
    const bodies = Array.from(container.querySelectorAll("tbody"));
    expect(bodies).toHaveLength(2);
    expect(bodies[0].textContent).toContain("Archived A");
    expect(bodies[1].textContent).toContain("Archived B");
    expect(Array.from(bodies[0].querySelectorAll("td")).map((cell) => cell.textContent)).toContain(
      "12"
    );
    expect(Array.from(bodies[1].querySelectorAll("td")).map((cell) => cell.textContent)).toContain(
      "5"
    );
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });

  it("compares observed totals when the source teams and hero metadata are unavailable", async () => {
    const container = await mountStats(historical());
    const panel = await openTab(container, messages.matches.tab.breakdown);
    const totals = panel.querySelector(`[aria-label="${messages.matches.breakdown.totals}"]`)!;
    // Each total reads home : away, from the observed members of each participation.
    expect(totals.textContent).toContain("12");
    expect(totals.textContent).toContain("5");
    expect(totals.textContent!.indexOf("12")).toBeLessThan(totals.textContent!.indexOf("5"));
    expect(panel.textContent).toContain("Archived A");
    expect(panel.textContent).toContain("Archived B");
  });

  it("links observed handles through the canonical player name, never the handle, and leaves a nameless one unlinked", async () => {
    const container = await mountStats(historical());
    const links = (scope: ParentNode) =>
      Array.from(scope.querySelectorAll<HTMLAnchorElement>('a[href^="/users/"]')).map(
        (link) => [link.textContent, link.getAttribute("href")]
      );
    // The scoreboard: Archived B's member is shown, not linked.
    // The whole handle is the link; its `#tag` renders as faint text inside it.
    expect(links(container)).toEqual([["Observed 101#1", "/users/Canonical 101"]]);
    expect(container.textContent).toContain("Observed 102");

    // The breakdown names its player of the map (Archived A's, first by impact) through the same canonical name.
    const panel = await openTab(container, messages.matches.tab.breakdown);
    const hrefs = new Set(links(panel).map(([, href]) => href));
    expect(hrefs).toEqual(new Set(["/users/Canonical 101"]));
    expect(panel.textContent).toContain(messages.matches.breakdown.playerOfMap);
  });

  it("renders nothing for a match that is not a duel", () => {
    const lobby = match([
      { id: 1, name: "A", eliminations: 1 },
      { id: 2, name: "B", eliminations: 2 },
      { id: 3, name: "C", eliminations: 3 }
    ]);
    expect(renderToStaticMarkup(<MatchStats match={lobby} metadata={metadata} />)).toBe("");
  });
});

describe("encounter participation statistics", () => {
  it.each(["overview", "players"] as const)(
    "keeps retired-only observations visible in %s",
    async (view) => {
      const container = await mount(
        <SeriesStats
          matches={[{ ...historical(), encounter: seats(201, 202) }]}
          metadata={metadata}
          view={view}
        />
      );
      expect(container.textContent).toContain("Archived A");
      expect(container.textContent).toContain("Archived B");
      expect(container.textContent).toContain("12");
      expect(container.textContent).toContain("5");
    }
  );

  it("keeps mixed participations separate without pairing replacement seats", async () => {
    const encounter = seats(201, 202);
    const current = match(
      [
        { id: 201, name: "Current A", eliminations: 4 },
        { id: 202, name: "Current B", eliminations: 3 }
      ],
      { id: 8, map_index: 1, encounter }
    );
    const container = await mount(
      <SeriesStats
        matches={[{ ...historical(), encounter }, current]}
        metadata={metadata}
        view="players"
      />
    );
    const bodies = Array.from(container.querySelectorAll("tbody"));
    expect(bodies).toHaveLength(4);
    expect(bodies.map((body) => body.querySelector("tr")?.textContent)).toEqual([
      "Archived A · Participation #101 · Historical participation",
      "Archived B · Participation #102 · Historical participation",
      "Current A · Participation #201",
      "Current B · Participation #202"
    ]);
    expect(Array.from(bodies[0].querySelectorAll("td")).map((cell) => cell.textContent)).toContain(
      "12"
    );
    expect(Array.from(bodies[2].querySelectorAll("td")).map((cell) => cell.textContent)).toContain(
      "4"
    );
  }, 20_000);
});

describe("native nullable timeline", () => {
  const critical = messages.matches.timeline.critical;
  const environmental = messages.matches.timeline.environmental;

  /** The kill/mark row that carries a clock reading (the clock is the row's first cell). */
  const rowAt = (container: HTMLElement, clock: string) =>
    Array.from(container.querySelectorAll("span")).find((element) => element.textContent === clock)!.parentElement!;
  /** The row's actor: the first name cell, in whatever colour the row paints it. */
  const actorOf = (row: HTMLElement) =>
    Array.from(row.querySelectorAll("span")).find((element) => element.textContent === "—" && element.children.length === 0)!;

  it("preserves duplicate observations and chronological order with missing actors, entities and JSON", async () => {
    const container = await timeline([
      event({ t: 22 }),
      event(),
      event(),
      event({ t: 11, type: "ultimate_start" }),
      event({ type: "ultimate_start" }),
      event({ type: "ultimate_start" })
    ]);
    expect(timestamps(container)).toEqual(["0:11", "0:17", "0:17", "0:17", "0:17", "0:22"]);
    expect(container.querySelectorAll("img")).toHaveLength(0);
    expect(container.querySelector(`[aria-label="${critical}"]`)).toBeNull();
    expect(container.querySelector(`[aria-label="${environmental}"]`)).toBeNull();
  });

  it("renders event-only history rather than treating it as an empty kill feed", async () => {
    const container = await timeline([
      event({ type: "ultimate_start" }),
      event({ type: "ultimate_start" })
    ]);
    expect(timestamps(container)).toEqual(["0:17", "0:17"]);
    expect(container.textContent).not.toContain(messages.matches.timeline.empty);
  });

  it("does not assign an unknown actor to the away team or invent a fight", async () => {
    const container = await timeline([event()]);
    const actor = actorOf(rowAt(container, "0:17"));
    expect(actor.className).toContain("--aqt-fg-muted");
    expect(actor.className).not.toContain("--aqt-rose");
    expect(actor.className).not.toContain("--aqt-teal");
    expect(timestamps(container)).toEqual(["0:17"]);
    // No fight id: no numbered fight, no fight band to jump to.
    expect(container.textContent).not.toMatch(/Fight \d/);
    expect(container.querySelector('button[aria-label^="Fight"]')).toBeNull();
  });

  it("keeps known participation ownership and explicit flags", async () => {
    const container = await timeline([
      event({ actor_team_id: 2, data: { fight: 0, is_critical_hit: true, is_environmental: true } })
    ]);
    const actor = actorOf(rowAt(container, "0:17"));
    expect(actor.className).toContain("--aqt-rose");
    expect(container.querySelector(`[aria-label="${critical}"]`)).not.toBeNull();
    expect(container.querySelector(`[aria-label="${environmental}"]`)).not.toBeNull();
    // The kill belongs to a fight: its block and its band are both there.
    expect(container.textContent).toContain("Fight 1");
    expect(container.querySelectorAll('button[aria-label^="Fight"]')).toHaveLength(1);
  });
});
