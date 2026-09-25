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
// 4. The score column is headed by what the organizer says it counts
//    (`rules.score_label`, e.g. "Kills"), falling back to a translated "Score".
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it } from "vitest";

import en from "@/i18n/messages/en.json";
import type { FfaGameCell, FfaLobby, FfaLobbyRow } from "@/types/ffa.types";

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
    score: 10,
    points: 5,
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
    points: 10 - slot,
    games_played: 1,
    wins: 0,
    score: 42,
    games: [game(1)],
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
    rules: { placement_points: [10, 6, 3], score_points: 1, score_label: null },
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
          row(1, { games: [game(1), game(2, { state: null, placement: null, score: null, points: null })] }),
          row(2, { games: [game(1), game(2, { state: null, placement: null, score: null, points: null })] })
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
      lobby([row(1, { games: [game(1), game(2), game(3, { placement: 1, score: 31 })] })], {
        best_of: 2
      })
    );

    const cells = [...container.querySelectorAll("tbody tr [data-ffa-game]")];
    expect(cells.map((node) => node.getAttribute("data-ffa-game"))).toEqual(["1", "2", "3"]);
    expect(headers()).toContain("G3");
    expect(cells[2].textContent).toContain("31");
  });
});

describe("ffa lobby score column", () => {
  it("heads the score column with what the organizer says it counts", async () => {
    await mount(
      lobby([row(1)], {
        rules: { placement_points: [10], score_points: 1, score_label: "Kills" }
      })
    );

    expect(headers()).toContain("Kills");
    expect(headers()).not.toContain(en.ffa.colScore);
  });

  it("falls back to the translated score label when the organizer set none", async () => {
    await mount(lobby([row(1)]));

    expect(headers()).toContain(en.ffa.colScore);
  });
});
