// @vitest-environment happy-dom
import type { AnchorHTMLAttributes, ReactNode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { Encounter } from "@/types/encounter.types";

import { EncountersDataTable } from "./EncountersTable";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    prefetch: _prefetch,
    ...rest
  }: { href: string; children: ReactNode; prefetch?: boolean | null } & AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

const GAMES = new Map(
  (
    [
      { code: "overwatch", name: "Overwatch", short_name: "OW", icon: null, enabled: true },
      { code: "lol", name: "League of Legends", short_name: "LoL", icon: null, enabled: true }
    ] as DisciplineDescriptor[]
  ).map((game) => [game.code, game])
);

const seats = (one: [string, number], two: [string, number]) => [
  { id: 11, slot: 1, name: one[0], score: one[1], team: null },
  { id: 12, slot: 2, name: two[0], score: two[1], team: null }
];

const encounter = (id: number, patch: Record<string, unknown> = {}) =>
  ({
    id,
    discipline: "overwatch",
    status: "open",
    round: 1,
    best_of: 3,
    closeness: null,
    has_logs: false,
    is_live: false,
    is_final: false,
    played_at: null,
    scheduled_at: null,
    current_map_index: null,
    teams: [],
    matches: [],
    games: [],
    tournament: { name: "Cup" },
    ...patch
  }) as unknown as Encounter;

let root: Root;
let container: HTMLElement;

beforeEach(() => {
  container = document.body.appendChild(document.createElement("div"));
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function render(rows: Encounter[], props: { games?: Map<string, DisciplineDescriptor>; loading?: boolean } = {}) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
        <EncountersDataTable rows={rows} {...props} />
      </NextIntlClientProvider>
    );
  });
}

/** What a reader gets from column `index` of every table row: decorative marks are hidden. */
const column = (index: number) =>
  [...container.querySelectorAll("tbody tr")].map((row) => {
    const read = row.children[index].cloneNode(true) as HTMLElement;
    read.querySelectorAll('[aria-hidden="true"]').forEach((node) => node.remove());
    return read.textContent;
  });

describe("the encounters table's rows", () => {
  it("are each one real link to the encounter, named by both teams and the score, in the table and the phone cards", async () => {
    await render([
      encounter(1, { status: "completed", teams: seats(["Alpha", 2], ["Beta", 1]) }),
      encounter(2, { teams: seats(["Gamma", 0], ["Delta", 0]) })
    ]);

    const links = (scope: string) =>
      [...container.querySelectorAll<HTMLAnchorElement>(`${scope} a[href^="/encounters/"]`)].map((link) => [
        link.getAttribute("href"),
        link.getAttribute("aria-label")
      ]);
    const expected = [
      ["/encounters/1", "Alpha 2–1 Beta"],
      ["/encounters/2", "Gamma vs Delta"]
    ];

    expect(links("tbody")).toEqual(expected);
    expect(links("ul")).toEqual(expected);
    // No scripted row: the link is the only way in, so middle-click and new tabs just work.
    for (const row of container.querySelectorAll("tbody tr")) {
      expect(row.hasAttribute("tabindex")).toBe(false);
      expect(row.className).toContain("relative");
    }
    // CSS picks the layout: the cards below `md`, the table from it.
    expect(container.querySelector("ul")?.className).toContain("md:hidden");
    expect(container.querySelector("table")?.closest('[data-ui="card"]')?.className).toMatch(/\bhidden\b.*\bmd:block\b/);
  });

  it("show one pip per decided map, named by its winner", async () => {
    const game = (position: number, one: number, two: number) => ({
      id: position,
      position,
      map_id: null,
      state: "confirmed",
      teams: [
        { encounter_team_id: 11, score: one },
        { encounter_team_id: 12, score: two }
      ]
    });
    await render([
      encounter(1, {
        status: "completed",
        teams: seats(["Alpha", 2], ["Beta", 1]),
        games: [game(1, 2, 1), game(2, 0, 3), game(3, 2, 0)]
      })
    ]);

    const pips = container.querySelector('tbody [role="img"][aria-label^="Map results"]');
    expect(pips?.getAttribute("aria-label")).toBe(
      en.encounters.detail.pipsAria.replace("{summary}", "Alpha, Beta, Alpha")
    );
    const tones = [...(pips?.children ?? [])].map((pip) => pip.className);
    expect(tones).toHaveLength(3);
    expect(tones[0]).toContain("--aqt-teal");
    expect(tones[1]).toContain("--aqt-fg-dim");
    expect(column(1)[0]).toBe("2–1Bo3");
  });

  it("names the round the way the bracket does, and a final as the final", async () => {
    await render([
      encounter(1, { round: 3, is_final: true, stage: { name: "Playoffs" } }),
      encounter(2, { round: 3, stage: { name: "Groups" }, stage_item: { name: "Group A" } }),
      encounter(3, { round: -2, stage: { name: "Playoffs" } })
    ]);

    expect(column(2)).toEqual([
      `CupPlayoffs · ${en.bracket.final}`,
      "CupGroup A · Round 3",
      "CupPlayoffs · LB Round 2"
    ]);
  });
});

describe("the encounters table's game marks", () => {
  it("names each row's game in its matchup when the list spans games, an unknown game by its code", async () => {
    const rows = [encounter(1), encounter(2, { discipline: "lol" }), encounter(3, { discipline: "retired" })];
    await render(rows, { games: GAMES });

    const marks = [...container.querySelectorAll("tbody tr")].map((row) =>
      row.children[0].querySelector('[role="img"]')?.getAttribute("aria-label")
    );
    expect(marks).toEqual(["Overwatch", "League of Legends", "retired"]);
  });

  it("names no game when the list is one game's", async () => {
    await render([encounter(1)]);

    expect(container.querySelector('tbody td:first-child [role="img"]')).toBeNull();
  });
});

describe("the encounters table's closeness", () => {
  it("fills a block bar to the row's closeness, and marks a missing one", async () => {
    await render([encounter(1, { closeness: 0.734 }), encounter(2)]);

    const fill = container.querySelector<HTMLElement>("tbody [data-closeness-fill]");
    expect(fill?.style.width).toBe("73%");
    // An inline span ignores its width and the bar renders 0x0.
    expect(fill?.className).toMatch(/\bblock\b/);
    expect(column(3)).toEqual(["73%", "—"]);
  });

  it("names it on a phone card, where no column head does, and leaves a missing one out", async () => {
    await render([encounter(1, { closeness: 0.6 }), encounter(2)]);

    const cards = [...container.querySelectorAll("ul > li")].map((card) => card.textContent ?? "");
    expect(cards[0]).toContain("Closeness 60%");
    expect(cards[1]).not.toContain("Closeness");
    expect(cards[1]).not.toContain("—");
  });
});

describe("the encounters table's when column", () => {
  const tournament = { name: "Cup", start_date: "2019-06-01T00:00:00Z", end_date: "2019-06-08T00:00:00Z" };

  it("reads live from the server, a result by when it was played or else its tournament's day, a fixture by its slot", async () => {
    await render([
      encounter(1, { is_live: true }),
      encounter(2, { status: "completed", played_at: "2019-06-07T18:30:00Z", tournament }),
      // Imported history: its stamps are the import's, never the day it was played.
      encounter(3, { status: "completed", tournament, started_at: "2025-01-07T09:00:00Z" }),
      // A start stamp without the server's live flag is not live.
      encounter(4, { scheduled_at: "2026-11-02T17:00:00Z", started_at: "2026-11-02T17:05:00Z" }),
      encounter(5, { status: "pending" })
    ]);

    const cells = column(4);
    expect(cells[0]).toBe(`${en.common.now}${en.encounters.state.live}`);
    expect(cells[1]).toMatch(/^Jun 7/);
    expect(cells[2]).toBe("Jun 8, 2019");
    expect(cells[3]).toMatch(/^Nov 25:00\sPM$/);
    expect(cells[4]).toBe(en.encounters.state.upcoming);
  });

  it("keeps the date in sentence case on one line", async () => {
    await render([encounter(1, { status: "completed", tournament })]);

    const when = container.querySelector("tbody tr")?.children[4].firstElementChild;
    expect(when?.className).toContain("whitespace-nowrap");
    expect(when?.innerHTML).not.toContain("uppercase");
  });
});

describe("the encounters table while loading", () => {
  it("holds the layout with placeholder rows and cards", async () => {
    await render([], { loading: true });

    expect(container.querySelectorAll("tbody tr")).toHaveLength(8);
    expect(container.querySelectorAll("ul > li")).toHaveLength(8);
    expect(container.querySelector("table")?.getAttribute("aria-busy")).toBe("true");
  });
});
