// @vitest-environment happy-dom
//
// What a spectator can read off an FFA lobby table. The lobby IS the group's
// standings — there is no second screen that says who is through — so the four
// claims below are the whole contract of the table:
//
// 1. The cut-line sits under the lobby's own `advance_count`, not under a
//    stage-wide guess: a lobby that takes 2 of 5 draws it after the second row.
// 2. A tie cluster the line runs through says so. Those teams are separated by
//    the assigned order rather than by anything they did in the lobby, which is
//    the one thing the table must not print as a settled "advancing".
// 3. A game nobody has entered yet renders an EMPTY cell — never a zero. A `0`
//    there reads as "played, scored nothing", which is a different claim.
// 4. The table totals one column per PUBLIC column of the stage, headed by the
//    organizer's own label, and never prints a hidden column — the organizer's
//    own screens render this very table from the admin read, which carries the
//    hidden values, so the component is the one place that can guarantee it.
// 5. A played cell says what it paid: the place, the points, and — for a reader
//    who cannot see two stacked numbers — the public values of that game.
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it } from "vitest";

import en from "@/i18n/messages/en.json";
import type { FfaGameCell, FfaLobby, FfaLobbyRow, FfaRules } from "@/types/ffa.types";

import FfaLobbyTable from "./FfaLobbyTable";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function game(position: number, extra: Partial<FfaGameCell> = {}): FfaGameCell {
  return {
    position,
    state: "confirmed",
    placement: position,
    points: 5,
    stats: { kills: 10 },
    ...extra
  };
}

function row(slot: number, extra: Partial<FfaLobbyRow> = {}): FfaLobbyRow {
  return {
    team_id: slot,
    team_name: `Team ${slot}`,
    team_image_url: null,
    slot,
    position: slot,
    tie_group: null,
    is_pinned: false,
    points: 10 - slot,
    games_played: 1,
    wins: 0,
    stats: { kills: 42 },
    games: [game(1)],
    ...extra
  };
}

/** The default stage: one public column, places paid, so places are required. */
function rules(extra: Partial<FfaRules> = {}): FfaRules {
  return {
    columns: [{ key: "kills", label: "Kills", public: true, better: "higher" }],
    placement_points: [10, 6, 3],
    formula: "place_pts + kills",
    requires_placement: true,
    ...extra
  };
}

function lobby(rows: FfaLobbyRow[], extra: Partial<FfaLobby> = {}): FfaLobby {
  return {
    encounter_id: 500,
    tournament_id: 1,
    stage_id: 7,
    stage_item_id: 100,
    name: "Lobby A",
    status: "open",
    result_status: "none",
    best_of: 1,
    scheduled_at: null,
    advance_count: 2,
    rules: rules(),
    rows,
    ...extra
  };
}

let container: HTMLDivElement;
let root: Root;

async function mount(value: FfaLobby) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <FfaLobbyTable lobby={value} />
      </NextIntlClientProvider>
    );
  });
}

/** The 1-based row the cut-line sits under, or -1 when there is none. */
function cutAfterRow() {
  return [...container.querySelectorAll("tbody tr")].findIndex(
    (node) => node.querySelector("[data-ffa-cut]") != null
  );
}

function headers() {
  return [...container.querySelectorAll("thead th")].map((node) => node.textContent);
}

/** The total printed for one column on one row, or null when there is none. */
function statCell(slot: number, key: string) {
  const rows = [...container.querySelectorAll("tbody tr")];
  const node = rows[slot - 1]?.querySelector(`[data-ffa-stat="${key}"]`);
  return node ? node.textContent : null;
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

describe("ffa lobby cut-line", () => {
  it("draws the lobby's advance line under the second of five rows", async () => {
    await mount(lobby([1, 2, 3, 4, 5].map((slot) => row(slot))));

    expect(cutAfterRow()).toBe(2);
    expect(
      [...container.querySelectorAll("tbody tr[data-advancing] [data-ffa-rank]")].map(
        (node) => node.textContent
      )
    ).toEqual(["1", "2"]);
  });

  it("draws no line when the lobby advances everyone", async () => {
    await mount(lobby([1, 2].map((slot) => row(slot)), { advance_count: 2 }));

    expect(cutAfterRow()).toBe(-1);
  });
});

describe("ffa lobby ties", () => {
  it("marks the cluster the advance line runs through", async () => {
    // Rows 2 and 3 share `tie_group` 2: the engine never separated them, and
    // the line falls between them.
    await mount(
      lobby([
        row(1),
        row(2, { position: 2, tie_group: 2 }),
        row(3, { position: 3, tie_group: 2 }),
        row(4)
      ])
    );

    const tied = [...container.querySelectorAll("tbody tr[data-tie]")];
    expect(tied).toHaveLength(2);
    expect(tied.map((node) => node.querySelector("[data-ffa-status]")?.textContent)).toEqual([
      en.ffa.tieStatus,
      en.ffa.tieStatus
    ]);
    expect(tied[0].querySelector("[data-ffa-status]")?.getAttribute("title")).toBe(
      en.ffa.tieDecidesAdvance
    );
  });

  it("leaves a tie clear of the line unmarked", async () => {
    await mount(
      lobby([
        row(1),
        row(2),
        row(3, { position: 3, tie_group: 3 }),
        row(4, { position: 3, tie_group: 3 })
      ])
    );

    expect(container.querySelector("tbody tr[data-tie]")).toBeNull();
  });

  it("claims no ranks, ties or verdicts before the first game counts", async () => {
    // What the engine answers for a fresh lobby: every team level on every
    // tiebreaker, one cluster headed at 1, straddling the line. Printed as-is it
    // said "all 1st" and "the assigned order decides who advances".
    const unplayed = { games_played: 0, points: 0, tie_group: 1, games: [] };
    await mount(lobby([1, 2, 3, 4].map((slot) => row(slot, unplayed))));

    expect(
      [...container.querySelectorAll("tbody [data-ffa-rank]")].map((node) => node.textContent)
    ).toEqual(["—", "—", "—", "—"]);
    expect(container.querySelector("tbody tr[data-tie]")).toBeNull();
    expect(container.querySelector("tbody tr[data-advancing]")).toBeNull();
    expect(container.querySelector("[data-ffa-status]")).toBeNull();
    // The rule is known before any result is: the line still says who goes on.
    expect(cutAfterRow()).toBe(2);
  });
});

describe("ffa lobby game cells", () => {
  it("leaves the cell of a game nobody has entered empty", async () => {
    await mount(
      lobby(
        [
          row(1, { games: [game(1), game(2, { state: null, placement: null, points: null, stats: null })] }),
          row(2, { games: [game(1), game(2, { state: null, placement: null, points: null, stats: null })] })
        ],
        { best_of: 2 }
      )
    );

    const cells = [...container.querySelectorAll("tbody tr [data-ffa-game]")];
    expect(cells.map((node) => node.getAttribute("data-ffa-game"))).toEqual(["1", "2", "1", "2"]);
    expect(cells[1].textContent).toBe("");
    expect(cells[0].textContent).not.toBe("");
  });

  it("leaves a position the lobby has no cell for empty too", async () => {
    await mount(lobby([row(1, { games: [game(1)] })], { best_of: 3 }));

    const cells = [...container.querySelectorAll("tbody tr [data-ffa-game]")];
    expect(cells).toHaveLength(3);
    expect([cells[1].textContent, cells[2].textContent]).toEqual(["", ""]);
  });

  it("keeps a game recorded past a lowered games count on screen", async () => {
    // The organizer cut the series to 2 after game 3 was confirmed. The backend
    // keeps answering that cell (`_read_lobby`: `max(best_of, recorded)`) —
    // it still scores, and voiding it is the only way to finish the cut — so a
    // column count taken from `best_of` alone hid a counted game.
    await mount(
      lobby([row(1, { games: [game(1), game(2), game(3, { placement: 1, points: 31, stats: { kills: 31 } })] })], {
        best_of: 2
      })
    );

    const cells = [...container.querySelectorAll("tbody tr [data-ffa-game]")];
    expect(cells.map((node) => node.getAttribute("data-ffa-game"))).toEqual(["1", "2", "3"]);
    expect(headers()).toContain("G3");
    expect(cells[2].textContent).toContain("31");
  });
});

describe("ffa lobby stat columns", () => {
  it("totals one column per public column, headed by the organizer's label", async () => {
    await mount(
      lobby([row(1, { stats: { kills: 29, assists: 4 } })], {
        rules: rules({
          columns: [
            { key: "kills", label: "Kills", public: true, better: "higher" },
            { key: "assists", label: "Assists", public: true, better: "higher" }
          ]
        })
      })
    );

    // The label the organizer wrote, verbatim, and one column per public key —
    // the header row is not pinned whole here, because the `#` and status heads
    // carry sr-only text that says nothing about columns.
    expect(headers()).toContain("Kills");
    expect(headers()).toContain("Assists");
    expect(statCell(1, "kills")).toBe("29");
    expect(statCell(1, "assists")).toBe("4");
  });

  it("prints neither the header nor the values of a hidden column", async () => {
    // The organizer's own lobby page renders this table from the ADMIN read,
    // which still carries `deaths`. The same component renders the public
    // bracket, so dropping the column here is what keeps a hidden value from
    // ever reaching a spectator's DOM.
    await mount(
      lobby([row(1, { stats: { kills: 29, deaths: 777 } })], {
        rules: rules({
          columns: [
            { key: "kills", label: "Kills", public: true, better: "higher" },
            { key: "deaths", label: "Deaths", public: false, better: "lower" }
          ]
        })
      })
    );

    expect(headers()).not.toContain("Deaths");
    expect(statCell(1, "deaths")).toBeNull();
    expect(container.textContent).not.toContain("777");
  });

  it("totals a column the team never scored as zero", async () => {
    // A column added mid-stage: the games already played carry no key for it,
    // and an empty cell there would read as "not counted yet".
    await mount(lobby([row(1, { stats: {} })]));

    expect(statCell(1, "kills")).toBe("0");
  });
});

describe("ffa lobby played cells", () => {
  it("prints the place above the points the game paid", async () => {
    await mount(lobby([row(1, { games: [game(1, { placement: 3, points: 12.5 })] })]));

    const cell = container.querySelector("tbody tr [data-ffa-game='1']");
    expect(cell?.textContent).toContain("3");
    // Fractional points are the point of a custom formula; a rounded "12" or a
    // padded "12.0" would both be a different number than the one that scored.
    expect(cell?.textContent).toContain("12.5");
  });

  it("describes a cell with its place, points and public values", async () => {
    await mount(
      lobby([row(1, { games: [game(1, { placement: 3, points: 16, stats: { kills: 6, deaths: 2 } })] })], {
        rules: rules({
          columns: [
            { key: "kills", label: "Kills", public: true, better: "higher" },
            { key: "deaths", label: "Deaths", public: false, better: "lower" }
          ]
        })
      })
    );

    const described = container.querySelector("tbody tr [data-ffa-game='1'] [title]");
    expect(described?.getAttribute("title")).toBe(
      `${en.ffa.colPlace} 3, ${en.ffa.colPoints} 16, Kills 6`
    );
    expect(described?.textContent).toContain(`${en.ffa.colPlace} 3, ${en.ffa.colPoints} 16, Kills 6`);
    expect(described?.getAttribute("title")).not.toContain("Deaths");
  });
});

describe("ffa lobby legend", () => {
  it("shows the formula the lobby is actually scored by", async () => {
    // The risk the legend answers (spec §12): a formula edited mid-stage moves
    // every place silently. The table prints the rule it was scored by.
    await mount(lobby([row(1)], { rules: rules({ formula: "place_pts + kills * 2 - deaths" }) }));

    expect(container.querySelector("code")?.textContent).toBe("place_pts + kills * 2 - deaths");
    expect(container.textContent).toContain("10 · 6 · 3");
  });

  it("says nothing about place points when the stage pays none", async () => {
    await mount(lobby([row(1)], { rules: rules({ placement_points: [], formula: "kills" }) }));

    expect(container.textContent).not.toContain("10 · 6 · 3");
    expect(container.querySelector("code")?.textContent).toBe("kills");
  });
});
