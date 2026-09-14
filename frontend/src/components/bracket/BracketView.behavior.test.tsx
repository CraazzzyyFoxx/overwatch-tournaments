// @vitest-environment happy-dom
//
// Behaviour of the assembled tree as a viewer sees it: the live-stream indicator
// on a slot row, the opening scroll position, round headers clear of cards, and
// which connectors are drawn. The layout maths itself is covered by
// `layout.test.ts` and `bracket-view.helpers.test.ts`.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Encounter } from "@/types/encounter.types";
import type { StreamEntry } from "@/types/stream.types";

import { BracketView } from "./BracketView";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({
  usePathname: () => "/tournaments/1/bracket",
  useSearchParams: () => new URLSearchParams("stage=3")
}));

// The bracket card links out to the encounter and the pre-game room. Plain
// anchors here: `next/link` needs an App Router context this test has no reason
// to stand up, and the assertions are about the indicator, not routing.
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  )
}));

// `EncounterRostersModal` fetches only once opened, but importing the real
// service drags in the axios client for nothing.
vi.mock("@/services/encounter.service", () => ({
  default: { getEncounter: vi.fn() }
}));

function encounter(overrides: Partial<Encounter> = {}): Encounter {
  return {
    id: 1,
    created_at: new Date(0),
    updated_at: null,
    name: "Nova vs Void",
    home_team_id: 7,
    away_team_id: 8,
    score: { home: 2, away: 1 },
    round: 1,
    best_of: 3,
    tournament_id: 1,
    stage_id: 3,
    stage_item_id: 4,
    challonge_id: null,
    status: "completed",
    closeness: null,
    has_logs: false,
    result_status: "confirmed",
    scheduled_at: null,
    started_at: null,
    ended_at: null,
    current_map_index: null,
    confirmed_at: null,
    matches: [],
    home_team: null as never,
    away_team: null as never,
    tournament: null as never,
    stage: null,
    stage_item: null,
    ...overrides
  };
}

function stream(overrides: Partial<StreamEntry> & { channel: string }): StreamEntry {
  return {
    platform: "twitch",
    url: `https://twitch.tv/${overrides.channel}`,
    live: true,
    title: null,
    game_name: null,
    viewer_count: null,
    thumbnail_url: null,
    started_at: null,
    player: { id: 1, name: "Aria", avatar_url: null, team: { id: 7, name: "Nova" } },
    ...overrides
  };
}

let container: HTMLDivElement;
let root: Root | null = null;

function render(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  root = createRoot(container);
  act(() =>
    root!.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          {ui}
        </NextIntlClientProvider>
      </QueryClientProvider>
    )
  );
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null;
  container.remove();
});

describe("BracketView live-stream indicator", () => {
  /** The dot is about a match still to be decided; the default fixture is settled. */
  const inPlay = () => encounter({ status: "open", score: { home: 1, away: 0 }, started_at: "2026-01-01T10:00:00Z" });

  // The admin bracket passes no stream map. A required prop would have broken it,
  // so this is the regression guard for that call site.
  it("renders the slot rows unchanged when no stream map is given", () => {
    render(<BracketView encounters={[encounter()]} type="single_elimination" />);

    expect(container.textContent).toContain("Nova");
    expect(container.textContent).toContain("Void");
    expect(container.querySelectorAll("[data-team-id]")).toHaveLength(2);
    expect(container.querySelector("[data-live-team-stream]")).toBeNull();
  });

  it("marks only the side whose team is on air", () => {
    render(
      <BracketView
        encounters={[inPlay()]}
        type="single_elimination"
        liveTeamStreams={new Map([[7, stream({ channel: "aria", viewer_count: 412 })]])}
      />
    );

    const indicators = container.querySelectorAll("[data-live-team-stream]");
    expect(indicators).toHaveLength(1);
    expect(indicators[0].closest("[data-team-id]")?.getAttribute("data-team-id")).toBe("7");
  });

  it("names the streamer and the audience for assistive tech and for the mouse", () => {
    render(
      <BracketView
        encounters={[inPlay()]}
        type="single_elimination"
        liveTeamStreams={new Map([[7, stream({ channel: "aria", viewer_count: 412 })]])}
      />
    );

    const indicator = container.querySelector("[data-live-team-stream]");
    expect(indicator?.getAttribute("role")).toBe("img");
    expect(indicator?.getAttribute("aria-label")).toBe("Aria is streaming live · 412 viewers");
    expect(indicator?.getAttribute("title")).toBe("Aria is streaming live · 412 viewers");
  });

  // YouTube and other hosts are never polled for a viewer count, so the label has
  // to stand on the player's name alone rather than claim "0 viewers".
  it("drops the audience from the label when the platform reports no count", () => {
    render(
      <BracketView
        encounters={[inPlay()]}
        type="single_elimination"
        liveTeamStreams={new Map([[7, stream({ channel: "aria", viewer_count: null })]])}
      />
    );

    expect(container.querySelector("[data-live-team-stream]")?.getAttribute("aria-label")).toBe(
      "Aria is streaming live"
    );
  });

  // Indication, not navigation: the Streams tab owns the links.
  it("carries the animated dot without becoming a link or a tab stop", () => {
    render(
      <BracketView
        encounters={[inPlay()]}
        type="single_elimination"
        liveTeamStreams={new Map([[7, stream({ channel: "aria", viewer_count: 412 })]])}
      />
    );

    const indicator = container.querySelector("[data-live-team-stream]") as HTMLElement;
    expect(indicator.tagName).toBe("SPAN");
    expect(indicator.hasAttribute("href")).toBe(false);
    expect(indicator.hasAttribute("tabindex")).toBe(false);
    expect(indicator.querySelector("a")).toBeNull();
    // The site's single liveness language, reused rather than re-styled.
    expect(indicator.className).toContain("status-pill");
    expect(indicator.className).toContain("live");
    expect(indicator.querySelector(".dot")?.getAttribute("aria-hidden")).toBe("true");
  });

  // An unfilled slot has no team, so there is nothing for a stream to belong to
  // even if a stale team id survived on the encounter.
  it("leaves an unseeded slot unmarked", () => {
    render(
      <BracketView
        encounters={[encounter({ name: "TBD vs Void", status: "open", score: { home: 0, away: 0 } })]}
        type="single_elimination"
        liveTeamStreams={new Map([[7, stream({ channel: "aria", viewer_count: 412 })]])}
      />
    );

    expect(container.querySelector("[data-live-team-stream]")).toBeNull();
  });

  // A team on air is news for the match it is playing, not for one it already won.
  it("drops the indicator once the match is settled", () => {
    render(
      <BracketView
        encounters={[encounter()]}
        type="single_elimination"
        liveTeamStreams={new Map([[7, stream({ channel: "aria", viewer_count: 412 })]])}
      />
    );

    expect(container.querySelector("[data-live-team-stream]")).toBeNull();
  });
});

// The tree is routinely wider than its scroller, and round 1 of a running
// playoff was decided days ago. So the canvas opens on the round in play.
describe("BracketView opening round", () => {
  const scroller = () => container.querySelector<HTMLDivElement>("[data-bracket-focused]");
  /** The laid-out x of a match's card, which is its round's column. */
  const columnX = (matchId: number) =>
    Number.parseFloat(
      container.querySelector<HTMLDivElement>(`[data-match-id="${matchId}"]`)!.style.left
    );

  const threeRounds = [
    encounter({ id: 1, round: 1, status: "completed" }),
    encounter({ id: 2, round: 1, status: "completed" }),
    encounter({ id: 3, round: 2, status: "open" }),
    encounter({ id: 4, round: 3, status: "open" })
  ];

  // The scroller has no measured width here, so the offset lands at the column
  // rather than centred on it — enough to say WHICH column was chosen, which is
  // the whole decision. Bracketing it by the next column keeps the assertion
  // independent of the layout's spacing constants.
  const opensOnColumnOf = (el: HTMLDivElement, matchId: number, nextMatchId: number) =>
    el.scrollLeft >= columnX(matchId) && el.scrollLeft < columnX(nextMatchId);

  it("scrolls the canvas to the first round that still has an unsettled match", () => {
    render(<BracketView encounters={threeRounds} type="single_elimination" />);

    // Round 2 (match 3), not round 1 (match 1) sitting at the canvas origin.
    expect(opensOnColumnOf(scroller()!, 3, 4)).toBe(true);
  });

  it("leaves a settled bracket on its last round", () => {
    render(
      <BracketView
        encounters={threeRounds.map((match) => ({ ...match, status: "completed" }))}
        type="single_elimination"
      />
    );

    // Round 3 (match 4) is last, so nothing lies to its right to bracket it.
    expect(scroller()!.scrollLeft).toBeGreaterThanOrEqual(columnX(4));
  });

  it("yields to a deep link, which scrolls its own node into view instead", () => {
    render(
      <BracketView encounters={threeRounds} type="single_elimination" highlightMatchId={1} />
    );

    expect(scroller()).toBeNull();
  });
});

// The grand-final column is centred in the whole bracket height, which used to
// put its card on top of its own round header.
describe("BracketView round headers", () => {
  const top = (el: Element) => Number.parseFloat((el as HTMLElement).style.top);

  // A shallow bracket — one semi, one grand final — is the shape that broke:
  // the GF column is centred in a bracket barely taller than one card.
  it("keeps every card clear of the header row", () => {
    render(
      <BracketView
        type="double_elimination"
        encounters={[
          encounter({ id: 1, round: 1, status: "open" }),
          encounter({ id: 2, round: 2, status: "open" })
        ]}
      />
    );

    const headers = [...container.querySelectorAll("[data-round-header]")];
    expect(headers).toHaveLength(2);

    for (const card of container.querySelectorAll("[data-match-id]")) {
      const above = headers.filter((header) => top(header) <= top(card));
      expect(above.every((header) => top(card) - top(header) >= 24)).toBe(true);
    }
  });

  // The tree is the one surface that drops the "UB " prefix: its upper rounds
  // are their own row of columns. The lower bracket keeps "LB", or the picture
  // carries two headers reading "Final" for two different matches.
  it("names the upper bracket bare and the lower bracket by side", () => {
    render(
      <BracketView
        type="double_elimination"
        encounters={[
          encounter({ id: 1, round: 1, status: "open" }),
          encounter({ id: 2, round: 1, status: "open" }),
          encounter({ id: 3, round: 2, status: "open" }),
          encounter({ id: 4, round: -1, status: "open" }),
          encounter({ id: 5, round: -2, status: "open" }),
          encounter({ id: 6, round: 3, status: "open" })
        ]}
      />
    );

    // Keyed by header id, not DOM order: the top row of headers is a sticky
    // layer drawn before the lower bracket's, so document order is not play order.
    expect(
      Object.fromEntries(
        [...container.querySelectorAll("[data-round-header]")].map((header) => [
          header.getAttribute("data-round-header"),
          header.textContent?.trim()
        ])
      )
    ).toEqual({
      "upper-header-1": "Semifinal",
      "upper-header-2": "Final",
      "lower-header--1": "LB Round 1",
      "lower-header--2": "LB Final",
      "final-header-3": "Grand Final"
    });
  });
});

// Connector lines: the bracket's own advancement edges are the truth, and a
// match that records none still gets the column-index guess — one wired match
// used to switch inference off for the WHOLE bracket, leaving every unrecorded
// match (a hand-created encounter, a legacy stage) floating unconnected.
describe("BracketView connectors", () => {
  it("draws recorded feeders and infers only the matches that record none", () => {
    render(
      <BracketView
        type="single_elimination"
        encounters={[
          encounter({ id: 1, round: 1 }),
          encounter({ id: 2, round: 1 }),
          encounter({ id: 3, round: 1 }),
          encounter({ id: 4, round: 1 }),
          encounter({
            id: 5,
            round: 2,
            sources: [
              { encounter_id: 1, role: "winner", slot: "home" },
              { encounter_id: 2, role: "winner", slot: "away" }
            ]
          }),
          encounter({ id: 6, round: 2 }),
          encounter({ id: 7, round: 3 })
        ]}
      />
    );

    const drawn = [...container.querySelectorAll("[data-edge]")].map((path) =>
      path.getAttribute("data-edge")
    );
    expect(new Set(drawn)).toEqual(
      new Set(["edge-1-5", "edge-2-5", "edge-3-6", "edge-4-6", "edge-5-7", "edge-6-7"])
    );
  });

  it("never guesses a second feeder into a match that names its own", () => {
    render(
      <BracketView
        type="single_elimination"
        encounters={[
          encounter({ id: 1, round: 1 }),
          encounter({ id: 2, round: 1 }),
          // Recorded as fed by match 1 alone — a bye on the other side. The
          // column mapping would have paired match 2 into it as well.
          encounter({
            id: 3,
            round: 2,
            sources: [{ encounter_id: 1, role: "winner", slot: "home" }]
          })
        ]}
      />
    );

    const drawn = [...container.querySelectorAll("[data-edge]")].map((path) =>
      path.getAttribute("data-edge")
    );
    expect(drawn).toEqual(["edge-1-3"]);
  });
});

// Rearrange mode: offered only to a caller that can swap slots, and even then
// only the rows of matches nothing has happened to yet can be picked up — the
// server refuses settled and live matches, so the view never offers them.
describe("BracketView rearrange mode", () => {
  const toggle = () => container.querySelector<HTMLButtonElement>("[data-bracket-rearrange]");

  it("offers no rearrange control to a viewer that cannot swap", () => {
    render(<BracketView encounters={[encounter()]} type="single_elimination" />);
    expect(toggle()).toBeNull();
  });

  it("unlocks only the untouched matches' team rows when switched on", () => {
    render(
      <BracketView
        type="single_elimination"
        encounters={[
          encounter({ id: 1, round: 1, status: "completed" }),
          encounter({ id: 2, round: 1, status: "open", result_status: "none", home_team_id: 9, away_team_id: 10 }),
          encounter({
            id: 3,
            round: 1,
            status: "open",
            result_status: "none",
            started_at: "2026-01-01T10:00:00Z",
            home_team_id: 11,
            away_team_id: 12
          }),
          encounter({ id: 4, round: 2, status: "open", result_status: "none", home_team_id: 0, away_team_id: 0 })
        ]}
        onSwapSlots={() => undefined}
      />
    );

    expect(container.querySelector("[data-slot-draggable]")).toBeNull();
    act(() => toggle()!.click());

    expect(toggle()!.getAttribute("aria-pressed")).toBe("true");
    expect(container.querySelector("[data-bracket-rearrange-hint]")).not.toBeNull();
    const draggable = [...container.querySelectorAll("[data-slot-draggable]")].map((row) =>
      row.closest("[data-match-id]")?.getAttribute("data-match-id")
    );
    // Match 1 is played, match 3 is live, match 4 has no team to pick up.
    expect(draggable).toEqual(["2", "2"]);
  });
});
