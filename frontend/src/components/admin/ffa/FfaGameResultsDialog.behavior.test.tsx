// @vitest-environment happy-dom
//
// What the organizer's game-entry dialog promises:
//
// 1. One line per participant leaves for the server, carrying a value for every
//    column of the stage — including the columns a spectator never sees — and a
//    blank is not one of them: a lobby is scored as a whole, so a team the
//    organizer has not got to yet must hold the request back rather than be
//    recorded on zero.
// 2. A rejection is readable: the server answers a machine code, and the
//    organizer sees the sentence for that code rather than a raw enum token.
// 3. Correcting a game that has already been played never leaves without a
//    reason. The server refuses it, and spending a round trip to learn that
//    loses the numbers the organizer just typed.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { ApiError } from "@/lib/api/error";
import type { FfaGameCell, FfaLobby, FfaLobbyRow, FfaRules } from "@/types/ffa.types";

import { FfaGameResultsDialog } from "./FfaGameResultsDialog";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const setGameResults = vi.fn();

vi.mock("@/services/ffa.service", () => ({
  default: {
    getStage: vi.fn(),
    getLobby: vi.fn(),
    setGameResults: (...args: unknown[]) => setGameResults(...args),
    cancelGame: vi.fn(),
    setGamesCount: vi.fn()
  }
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/admin/tournaments/84/matches/lobbies",
  useSearchParams: () => new URLSearchParams()
}));

function row(slot: number, games: FfaGameCell[] = []): FfaLobbyRow {
  return {
    team_id: slot,
    team_name: `Team ${slot}`,
    team_image_url: null,
    slot,
    position: slot,
    tie_group: null,
    is_pinned: false,
    points: 0,
    games_played: games.length,
    wins: 0,
    stats: {},
    games
  };
}

/**
 * The stage as the ADMIN read answers it: one public column and one hidden one,
 * places paid. The dialog is only ever mounted from a screen that reads
 * `getStageAdmin`, which is why `deaths` is here at all.
 */
function rules(extra: Partial<FfaRules> = {}): FfaRules {
  return {
    columns: [
      { key: "kills", label: "Kills", public: true, better: "higher" },
      { key: "deaths", label: "Deaths", public: false, better: "lower" }
    ],
    placement_points: [10, 6, 3],
    formula: "place_pts + kills - deaths",
    requires_placement: true,
    ...extra
  };
}

function lobby(rows: FfaLobbyRow[], extra: Partial<FfaLobby> = {}): FfaLobby {
  return {
    encounter_id: 500,
    tournament_id: 84,
    stage_id: 7,
    stage_item_id: 100,
    name: "Lobby A",
    status: "open",
    result_status: "none",
    best_of: 3,
    scheduled_at: null,
    advance_count: 2,
    rules: rules(),
    rows,
    ...extra
  };
}

let root: Root;

async function mount(value: FfaLobby, position: number) {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <FfaGameResultsDialog lobby={value} position={position} open onOpenChange={() => {}} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
}

function field(label: string): HTMLInputElement {
  const node = document.body.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`);
  if (!node) throw new Error(`no field labelled ${label}`);
  return node;
}

async function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function save() {
  const button = Array.from(document.body.querySelectorAll("button")).find(
    (node) => node.getAttribute("type") === "submit"
  );
  await act(async () => {
    button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  // The mutation settles across a microtask and a timer before React commits.
  for (let turn = 0; turn < 4; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

beforeEach(() => {
  document.body.innerHTML = "";
  setGameResults.mockReset().mockResolvedValue(lobby([row(1), row(2), row(3)]));
});

describe("entering an FFA game", () => {
  it("sends a value for every column of every team, hidden ones included", async () => {
    await mount(lobby([row(1), row(2), row(3)]), 2);

    for (const slot of [1, 2, 3]) {
      await type(field(`Place for Team ${slot}`), String(slot));
      await type(field(`Kills for Team ${slot}`), String(12 - slot));
      await type(field(`Deaths for Team ${slot}`), String(slot));
    }
    await save();

    expect(setGameResults).toHaveBeenCalledWith(500, 2, {
      results: [
        { team_id: 1, placement: 1, stats: { kills: 11, deaths: 1 } },
        { team_id: 2, placement: 2, stats: { kills: 10, deaths: 2 } },
        { team_id: 3, placement: 3, stats: { kills: 9, deaths: 3 } }
      ],
      reason: null
    });
  });

  it("offers the hidden column and says it is not shown to spectators", async () => {
    await mount(lobby([row(1)]), 1);

    // The value exists and is entered here; what `public: false` buys is that
    // the public read never answers it — which the organizer has to be told,
    // because this form is the only place the column is visible at all.
    const hidden = field("Deaths for Team 1");
    expect(hidden).not.toBeNull();
    expect(document.body.textContent).toContain("hidden from viewers");
  });

  it("keeps a valid grid for a placement-only stage, whose lines carry no stats", async () => {
    await mount(lobby([row(1), row(2)], { rules: rules({ columns: [], formula: "place_pts" }) }), 1);

    // `repeat(0, …)` is invalid CSS: a browser drops the whole track list and
    // every team's fields fall into one column. happy-dom evaluates no CSS, so
    // the track list itself is the observable property.
    const grid = document.body.querySelector<HTMLElement>('[style*="grid-template-columns"]');
    expect(grid?.style.gridTemplateColumns).toBe("minmax(7rem, 1fr) 5rem");

    await type(field("Place for Team 1"), "1");
    await type(field("Place for Team 2"), "2");
    await save();

    expect(setGameResults).toHaveBeenCalledWith(500, 1, {
      results: [
        { team_id: 1, placement: 1, stats: {} },
        { team_id: 2, placement: 2, stats: {} }
      ],
      reason: null
    });
  });

  it("holds the request back while a column is blank, rather than sending a zero", async () => {
    // A forgotten value used to leave as `0` — a line the server accepts, so
    // `ffa_result_missing_stat` could never catch it. Nothing is sent until the
    // zero is typed on purpose.
    await mount(lobby([row(1), row(2)]), 2);

    await type(field("Kills for Team 1"), "10");
    await type(field("Deaths for Team 1"), "1");
    await type(field("Kills for Team 2"), "7");
    await save();

    expect(setGameResults).not.toHaveBeenCalled();
    expect(field("Deaths for Team 2").getAttribute("aria-invalid")).toBe("true");
    expect(field("Kills for Team 2").getAttribute("aria-invalid")).toBeNull();

    await type(field("Deaths for Team 2"), "0");
    await type(field("Place for Team 1"), "1");
    await type(field("Place for Team 2"), "2");
    await save();

    expect(setGameResults).toHaveBeenCalledWith(500, 2, {
      results: [
        { team_id: 1, placement: 1, stats: { kills: 10, deaths: 1 } },
        { team_id: 2, placement: 2, stats: { kills: 7, deaths: 0 } }
      ],
      reason: null
    });
  });

  it("asks for a place only when the stage's formula reads one", async () => {
    await mount(
      lobby([row(1)], { rules: rules({ formula: "kills - deaths", requires_placement: false }) }),
      1
    );

    expect(document.body.textContent).toContain("Place (optional)");

    await type(field("Kills for Team 1"), "4");
    await type(field("Deaths for Team 1"), "0");
    await save();

    // No place typed, and none invented: the server derives it from the points.
    expect(setGameResults).toHaveBeenCalledWith(500, 1, {
      results: [{ team_id: 1, placement: null, stats: { kills: 4, deaths: 0 } }],
      reason: null
    });
  });

  it("shows the sentence for the code the server refused with", async () => {
    setGameResults.mockRejectedValue(
      new ApiError(422, [
        { msg: "Each place from 1 to N must be taken exactly once", code: "ffa_result_invalid_placement" }
      ])
    );
    await mount(lobby([row(1), row(2), row(3)]), 1);

    for (const slot of [1, 2, 3]) {
      await type(field(`Kills for Team ${slot}`), "4");
      await type(field(`Deaths for Team ${slot}`), "0");
    }
    await type(field("Place for Team 1"), "1");
    // Two firsts: the server is the one that knows this is not a permutation.
    await type(field("Place for Team 2"), "1");
    await type(field("Place for Team 3"), "2");
    await save();

    expect(document.body.textContent).toContain(en.ffa.errors.ffa_result_invalid_placement);
  });

  it("starts a correction from the values being corrected", async () => {
    const played = (slot: number) =>
      row(slot, [
        {
          position: 1,
          state: "confirmed",
          placement: slot,
          points: 5,
          stats: { kills: 5, deaths: slot }
        }
      ]);
    await mount(lobby([played(1), played(2), played(3)]), 1);

    expect(field("Kills for Team 2").value).toBe("5");
    expect(field("Deaths for Team 2").value).toBe("2");

    await save();

    expect(setGameResults).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain(en.ffa.errors.ffa_reason_required);

    await type(field("Reason"), "Scoreboard screenshot was misread");
    await save();

    expect(setGameResults).toHaveBeenCalledWith(500, 1, {
      results: [
        { team_id: 1, placement: 1, stats: { kills: 5, deaths: 1 } },
        { team_id: 2, placement: 2, stats: { kills: 5, deaths: 2 } },
        { team_id: 3, placement: 3, stats: { kills: 5, deaths: 3 } }
      ],
      reason: "Scoreboard screenshot was misread"
    });
  });
});
