// @vitest-environment happy-dom
//
// The history's dossier reads an event's run lazily, once: going back to an event already opened reads nothing.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { UserTournament, UserTournamentEntry, UserTournamentList } from "@/types/user.types";

import TournamentsHistory from "./TournamentsHistory";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const { getUserTournamentEncounters } = vi.hoisted(() => ({
  getUserTournamentEncounters: vi.fn(async (_userId: number, tournamentId: number) =>
    Array.from({ length: tournamentId }, (_, index) => ({ id: index }))
  )
}));

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock("@/services/user.service", () => ({ default: { getUserTournamentEncounters } }));
vi.mock("@/hooks/useDisciplineMetadata", () => ({
  useDisciplineMetadata: () => ({ data: undefined, isError: false, refetch: vi.fn() })
}));
vi.mock("@/app/(site)/users/components/tournaments/TournamentsPlacementTimeline", () => ({ default: () => null }));
// The dossier as what it is handed: the selected event, its grid and its run, or the loading state.
vi.mock("@/app/(site)/users/components/tournaments/TournamentDossier", () => ({
  default: ({
    tournament,
    loadingEncounters
  }: {
    tournament: UserTournamentEntry | null;
    loadingEncounters: boolean;
  }) => (
    <output>
      {loadingEncounters
        ? "loading"
        : `${tournament?.name}: ${tournament?.encounters.length} encounters on ${tournament?.division_grid_version?.label ?? "no grid"}`}
    </output>
  )
}));

// Cup 3 names the list's one grid version; Cup 2 none.
const tournaments = {
  results: [3, 2].map(
    (id) =>
      ({
        id,
        name: `Cup ${id}`,
        workspace_id: 1,
        discipline: "overwatch",
        team: "T",
        placement: 1,
        count_teams: 8,
        won: 1,
        lost: 0,
        draw: 0,
        maps_won: 2,
        maps_lost: 0,
        division_grid_version_id: id === 3 ? 8 : null,
        role: null
      }) as unknown as UserTournament
  ),
  division_grid_versions: [{ id: 8, label: "New Era" }]
} as unknown as UserTournamentList;

let container: HTMLDivElement;
let root: Root;

const settle = () =>
  act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
const dossier = () => container.querySelector("output")?.textContent;
const select = async (name: string) => {
  const row = [...container.querySelectorAll<HTMLButtonElement>("button[aria-pressed]")].find((node) =>
    node.textContent?.includes(name)
  );
  expect(row).toBeDefined();
  await act(async () => row!.click());
  await settle();
};

beforeEach(() => {
  getUserTournamentEncounters.mockClear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

it("reads each event's run once, so going back to an event reads nothing, and draws each on its own grid", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          <TournamentsHistory tournaments={tournaments} selfUserId={7} tournamentsWon={2} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
  expect(dossier()).toBe("Cup 3: 3 encounters on New Era");

  await select("Cup 2");
  expect(dossier()).toBe("Cup 2: 2 encounters on no grid");

  await select("Cup 3");
  expect(dossier()).toBe("Cup 3: 3 encounters on New Era");
  expect(getUserTournamentEncounters.mock.calls).toEqual([
    [7, 3],
    [7, 2]
  ]);
});

it("lists every day of a season as its own event, never grouped", async () => {
  const days = {
    results: [2, 1].map((id) => ({ ...tournaments.results[0], id, name: `Weekly | Day ${id}` }) as UserTournament),
    division_grid_versions: []
  } as unknown as UserTournamentList;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          <TournamentsHistory tournaments={days} selfUserId={7} tournamentsWon={0} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
  const rows = [...container.querySelectorAll<HTMLButtonElement>("button[aria-pressed]")].map((n) => n.textContent ?? "");
  expect(rows.filter((text) => text.includes("Weekly | Day"))).toHaveLength(2);
  expect(dossier()).toBe("Weekly | Day 2: 2 encounters on no grid");
});
