// @vitest-environment happy-dom
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Encounter, EncounterTeam, Match } from "@/types/encounter.types";
import type { Tournament } from "@/types/tournament.types";

import { MatchRow } from "./MatchRow";

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
  }: {
    href: string;
    children: React.ReactNode;
    prefetch?: boolean | null;
  } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

const TOURNAMENT_ID = 88;
const ENCOUNTER_ID = 500;
const TEAL = "text-[color:var(--aqt-teal)]";

function seat(slot: number, name: string, score: number): EncounterTeam {
  return {
    id: 1000 + slot,
    slot,
    team_id: slot,
    name,
    seed: null,
    score,
    placement: null,
    active: true,
    team: null
  };
}

/**
 * Seats listed slot 2 first, as the wire may send them: the row must still draw slot 1 on the left. The series
 * stands 2–1 for slot 1.
 */
const SEATS = [seat(2, "Bravo", 1), seat(1, "Alpha", 2)];

/** One parsed map; its log lists slot 2's participant first too. */
function mapRow(
  id: number,
  index: number,
  slotOne: number,
  slotTwo: number,
  logName: string | null
): Match {
  const participant = (slot: number, score: number, position: number) => ({
    encounter_team_id: 1000 + slot,
    slot,
    source_position: position,
    tournament_team_id: slot,
    name: slot === 1 ? "Alpha" : "Bravo",
    result: null,
    team_facts: { score }
  });
  return {
    id,
    created_at: "1970-01-01T00:00:00Z",
    updated_at: null,
    played_at: null,
    workspace_id: 1,
    discipline: "overwatch",
    encounter_game_id: null,
    participants: [participant(2, slotTwo, 0), participant(1, slotOne, 1)],
    duration_s: 600,
    encounter_id: ENCOUNTER_ID,
    map_id: 50 + index,
    map_index: index,
    mode: null,
    mode_id: null,
    log_name: logName,
    raw_status: null,
    raw_available: false,
    map: null,
    encounter: null
  };
}

function encounter(status: string, matches: Match[]): Encounter {
  return {
    id: ENCOUNTER_ID,
    created_at: new Date(0),
    updated_at: null,
    workspace_id: 1,
    discipline: "overwatch",
    name: "Alpha vs Bravo",
    slot_count: 2,
    scoring_preset: "wins",
    round: 1,
    best_of: 3,
    tournament_id: TOURNAMENT_ID,
    stage_id: null,
    stage_item_id: null,
    challonge_id: null,
    status,
    closeness: null,
    has_logs: matches.length > 0,
    result_status: "confirmed",
    result_source: "series_claim",
    result_version: 1,
    scheduled_at: null,
    started_at: null,
    ended_at: null,
    current_map_index: null,
    confirmed_at: null,
    played_at: null,
    is_live: status !== "completed",
    is_final: false,
    matches,
    games: [],
    teams: SEATS,
    // Not read by the row.
    tournament: {} as Tournament
  };
}

/** Slot 1 takes map 1 3–1 (logged), slot 2 takes map 2 2–0 (no log). Listed out of order. */
const MAPS = [mapRow(72, 2, 0, 2, null), mapRow(71, 1, 3, 1, "log-71.txt")];

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(row: Encounter) {
  act(() => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <MatchRow encounter={row} returnTo="/tournaments/anak-cup" />
      </NextIntlClientProvider>
    );
  });
}

/** The grid lines of the row: the series line first, then one per map, then the links line. */
const lines = () =>
  [...container.querySelectorAll<HTMLElement>("summary > div, details > div > div")].map(
    (line) => ({
      line,
      grid: line.className.split(" ").filter((token) => token.includes("grid-cols-")),
      cells: [...line.children] as HTMLElement[]
    })
  );

describe("MatchRow", () => {
  it("puts each map's score in the series score's columns, slot 1 on the left", () => {
    render(encounter("completed", MAPS));
    const [series, map1, map2] = lines();

    for (const map of [map1, map2]) expect(map.grid).toEqual(series.grid);
    const scoreCells = (cells: HTMLElement[]) =>
      [cells[2], cells[4]].map((cell) => cell.textContent);
    expect(scoreCells(series.cells)).toEqual(["2", "1"]);
    // Maps read in series order whatever the list order, each by the encounter's seats, not the log's.
    expect(map1.line.textContent).toContain("Map 1");
    expect(scoreCells(map1.cells)).toEqual(["3", "1"]);
    expect(scoreCells(map2.cells)).toEqual(["0", "2"]);
  });

  it("highlights the map winner's number and not the loser's", () => {
    render(encounter("completed", MAPS));
    const [, map1, map2] = lines();

    expect(map1.cells[2].classList.contains(TEAL)).toBe(true);
    expect(map1.cells[4].classList.contains(TEAL)).toBe(false);
    expect(map2.cells[2].classList.contains(TEAL)).toBe(false);
    expect(map2.cells[4].classList.contains(TEAL)).toBe(true);
  });

  it("links map stats only for maps with a log", () => {
    render(encounter("completed", MAPS));

    expect(container.querySelectorAll('a[href="/matches/71"]').length).toBeGreaterThan(0);
    expect(container.querySelector('a[href="/matches/72"]')).toBeNull();
    expect(container.textContent).toContain(en.tournamentDetail.matchRow.mapStats);
  });

  it("offers the pre-game room only until the series is completed", () => {
    const pregame = `a[href^="/tournaments/${TOURNAMENT_ID}/pregame/${ENCOUNTER_ID}"]`;

    render(encounter("open", MAPS));
    expect(container.querySelector(pregame)?.textContent).toBe(en.bracket.pregameRoom);
    expect(container.querySelector(`a[href="/encounters/${ENCOUNTER_ID}"]`)?.textContent).toBe(
      en.tournamentDetail.matchRow.matchPage
    );

    render(encounter("completed", MAPS));
    expect(container.querySelector(pregame)).toBeNull();
    expect(container.querySelector(`a[href="/encounters/${ENCOUNTER_ID}"]`)?.textContent).toBe(
      en.tournamentDetail.matchRow.matchPage
    );
  });

  it("makes a row without maps one link to the match, with nothing to unfold", () => {
    render(encounter("completed", []));

    expect(container.querySelector("details")).toBeNull();
    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe(`/encounters/${ENCOUNTER_ID}`);
    expect(links[0].getAttribute("aria-label")).toBe(en.bracket.viewMatch);
  });
});
