// @vitest-environment happy-dom
//
// A bracket card shows two truncated team names and nothing about who is on
// them, so checking a roster meant leaving for the encounter page and losing a
// 32-team tree's worth of scroll position. These tests cover what is new here —
// the lazy fetch behind the trigger and both sides landing in one dialog — not
// `EncounterRosterPanel`'s own row rendering, which the encounter page already
// exercises against the same unmodified component.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { canonicalDisplay } from "@/lib/player";
import type { Encounter } from "@/types/encounter.types";
import type { Player, Team } from "@/types/team.types";

import { EncounterRostersModal } from "./EncounterRostersModal";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getEncounter = vi.fn();

vi.mock("@/services/encounter.service", () => ({
  default: { getEncounter: (...args: unknown[]) => getEncounter(...args) }
}));

function player(id: number, name: string, overrides: Partial<Player> = {}): Player {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name,
    rank: 3000,
    division: 5,
    role: { dimension: "player_role", role: "damage" },
    tournament_id: 1,
    user_id: id,
    team_id: 1,
    is_newcomer: false,
    display: canonicalDisplay(name),
    is_newcomer_role: false,
    is_substitution: false,
    related_player_id: null,
    user: null,
    ...overrides
  };
}

function team(id: number, name: string, players: Player[]): Team {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name,
    image_url: null,
    avg_sr: 3000,
    total_sr: 15000,
    captain_id: players[0]?.user_id ?? 0,
    tournament_id: 1,
    players,
    tournament: null,
    placement: null,
    group: null
  };
}

const ENCOUNTER = {
  id: 4242,
  teams: [
    { id: 71, slot: 1, team_id: 1, name: "Bright Wolves", seed: null, score: 0, placement: null, active: true, team: team(1, "Bright Wolves", [player(11, "Kiriko Main"), player(12, "Second Wolf")]) },
    { id: 72, slot: 2, team_id: 2, name: "Quiet Foxes", seed: null, score: 0, placement: null, active: true, team: team(2, "Quiet Foxes", [player(21, "Silent Fox")]) }
  ],
  tournament: { division_grid_version: null }
} as unknown as Encounter;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

/** Let queued promise callbacks and React Query's own scheduling drain. */
async function settle(ticks = 3) {
  for (let index = 0; index < ticks; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <EncounterRostersModal
            encounterId={4242}
            teamNames={["Bright Wolves", "Quiet Foxes"]}
          />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
}

async function open() {
  const button = container.querySelector<HTMLButtonElement>(
    `button[aria-label="${en.bracket.viewRosters}"]`
  );
  if (!button) throw new Error("rosters trigger not rendered");
  await act(async () => {
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle();
}

describe("EncounterRostersModal", () => {
  it("fetches nothing until the trigger is clicked", async () => {
    getEncounter.mockResolvedValue(ENCOUNTER);
    await mount();

    expect(getEncounter).not.toHaveBeenCalled();

    await open();
    expect(getEncounter).toHaveBeenCalledWith(4242);
  });

  it("renders both sides' players in one dialog", async () => {
    getEncounter.mockResolvedValue(ENCOUNTER);
    await mount();
    await open();

    const text = document.body.textContent ?? "";
    expect(text).toContain("Bright Wolves vs Quiet Foxes");
    expect(text).toContain("Kiriko Main");
    expect(text).toContain("Second Wolf");
    expect(text).toContain("Silent Fox");
  });

  it("offers a retry instead of an empty dialog when the read fails", async () => {
    getEncounter.mockRejectedValue(new Error("boom"));
    await mount();
    await open();

    expect(document.body.textContent).toContain(en.common.pageState.error.title);
  });
});
