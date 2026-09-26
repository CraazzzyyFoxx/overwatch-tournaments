// @vitest-environment happy-dom
//
// What the organizer's game-entry dialog promises:
//
// 1. One line per participant leaves for the server, and a blank score is not
//    one of them: a lobby is scored as a whole, so a team the organizer has not
//    got to yet must hold the request back rather than be recorded on zero.
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
import type { FfaGameCell, FfaLobby, FfaLobbyRow } from "@/types/ffa.types";

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
    score: 0,
    games
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
    rules: { placement_points: [10, 6, 3], score_points: 1, score_label: null },
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
  it("sends a line for every team of the lobby once every score is in", async () => {
    await mount(lobby([row(1), row(2), row(3)]), 2);

    await type(field("Place for Team 1"), "1");
    await type(field("Score for Team 1"), "10");
    await type(field("Place for Team 2"), "2");
    await type(field("Score for Team 2"), "7");
    await type(field("Place for Team 3"), "3");
    await type(field("Score for Team 3"), "0");
    await save();

    expect(setGameResults).toHaveBeenCalledWith(500, 2, {
      results: [
        { team_id: 1, placement: 1, score: 10 },
        { team_id: 2, placement: 2, score: 7 },
        { team_id: 3, placement: 3, score: 0 }
      ],
      reason: null
    });
  });

  it("holds the request back while a team has no score, rather than recording a zero", async () => {
    // A forgotten team used to leave as `score: 0` — a line the server accepts,
    // so `ffa_result_missing_team` could never catch it. Nothing is sent until
    // the zero is typed on purpose.
    await mount(lobby([row(1), row(2), row(3)]), 2);

    await type(field("Score for Team 1"), "10");
    await type(field("Score for Team 2"), "7");
    await save();

    expect(setGameResults).not.toHaveBeenCalled();
    expect(field("Score for Team 3").getAttribute("aria-invalid")).toBe("true");
    expect(field("Score for Team 1").getAttribute("aria-invalid")).toBeNull();

    await type(field("Score for Team 3"), "0");
    await save();

    expect(setGameResults).toHaveBeenCalledWith(500, 2, {
      results: [
        { team_id: 1, placement: null, score: 10 },
        { team_id: 2, placement: null, score: 7 },
        { team_id: 3, placement: null, score: 0 }
      ],
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

    for (const slot of [1, 2, 3]) await type(field(`Score for Team ${slot}`), "4");
    await type(field("Place for Team 1"), "1");
    // Two firsts: the server is the one that knows this is not a permutation.
    await type(field("Place for Team 2"), "1");
    await type(field("Place for Team 3"), "2");
    await save();

    expect(document.body.textContent).toContain(en.ffa.errors.ffa_result_invalid_placement);
  });

  it("refuses to correct a played game until a reason is given", async () => {
    const played = (slot: number) =>
      row(slot, [{ position: 1, state: "confirmed", placement: slot, score: 5, points: 3 }]);
    await mount(lobby([played(1), played(2), played(3)]), 1);

    await save();

    expect(setGameResults).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain(en.ffa.errors.ffa_reason_required);

    await type(field("Reason"), "Scoreboard screenshot was misread");
    await save();

    expect(setGameResults).toHaveBeenCalledWith(500, 1, {
      results: [
        { team_id: 1, placement: 1, score: 5 },
        { team_id: 2, placement: 2, score: 5 },
        { team_id: 3, placement: 3, score: 5 }
      ],
      reason: "Scoreboard screenshot was misread"
    });
  });
});
