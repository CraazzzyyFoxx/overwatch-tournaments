// @vitest-environment happy-dom
//
// The profile's game surfaces (spec §6.6): the per-game tabs pick a game without
// touching the URL, the "never played" state widens the scope back to every game, and the cross-game lists mark
// each row with its game.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { EncounterWithUserStats, UserTournament } from "@/types/user.types";

import MatchesTable from "../matches/MatchesTable";
import TournamentList from "../tournaments/TournamentList";
import ProfileGameTabs from "./ProfileGameTabs";
import ProfileNotPlayed from "./ProfileNotPlayed";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const { selectScope, selectTab, refresh, gameSource } = vi.hoisted(() => ({
  selectScope: vi.fn(),
  selectTab: vi.fn(),
  refresh: vi.fn(),
  // Where the resolved game comes from: "url" when a valid `?discipline=` fixes the page's game.
  gameSource: { value: "default" }
}));

const OW = { code: "overwatch", name: "Overwatch", short_name: "OW", icon: null, enabled: true } as DisciplineDescriptor;
const LOL = { code: "lol", name: "League of Legends", short_name: "LoL", icon: null, enabled: true } as DisciplineDescriptor;

vi.mock("next/navigation", () => ({
  usePathname: () => "/users/Ana-1234",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh })
}));
vi.mock("@/hooks/useGameScope", () => ({
  useGameScope: () => ({
    axis: 1,
    games: [LOL, OW],
    resolution: { game: { kind: "game", code: "lol", source: gameSource.value }, pill: { kind: "all" }, tabs: true, scope: "all" },
    game: "lol",
    isError: false,
    refetch: vi.fn(),
    selectScope,
    selectTab
  })
}));
vi.mock("@/hooks/useGameDescriptors", () => ({
  useGameDescriptors: () => new Map([[OW.code, OW], [LOL.code, LOL]])
}));
vi.mock("@/hooks/useDisciplineMetadata", () => ({
  useDisciplineMetadata: () => ({ data: undefined, isError: false, refetch: vi.fn() })
}));
vi.mock("@/hooks/useCurrentWorkspace", () => ({
  useDivisionGrid: () => ({ tiers: [] })
}));

let container: HTMLDivElement;
let root: Root;

const render = async (node: ReactNode) => {
  await act(async () => {
    root.render(
      <QueryClientProvider client={new QueryClient()}>
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          {node}
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
};

const press = async (element: Element | null) => {
  expect(element).not.toBeNull();
  await act(async () => {
    element!.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    element!.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    (element as HTMLElement).click();
  });
};

beforeEach(() => {
  selectScope.mockClear();
  selectTab.mockClear();
  refresh.mockClear();
  gameSource.value = "default";
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

it("picks a per-game tab without writing the URL, then re-reads the page", async () => {
  await render(<ProfileGameTabs initial={{ stored: "all", lastGame: null, axis: 1, hostLockedWorkspaceId: null, disciplines: [LOL, OW] }} games={["lol", "overwatch"]} />);

  const tab = [...container.querySelectorAll('[role="tab"]')].find((node) => node.textContent?.includes("Overwatch"));
  await press(tab ?? null);
  expect(selectTab).toHaveBeenCalledWith("overwatch", { url: false });
  expect(refresh).toHaveBeenCalled();
});

it("shows no per-game tabs while a URL game fixes the page's game", async () => {
  gameSource.value = "url";
  await render(<ProfileGameTabs initial={{ stored: "all", lastGame: null, axis: 1, hostLockedWorkspaceId: null, disciplines: [LOL, OW] }} games={["lol", "overwatch"]} />);

  expect(container.querySelector('[role="tablist"]')).toBeNull();
});

it("widens a never-played game back to every game", async () => {
  await render(<ProfileNotPlayed player="Ana#1234" game="League of Legends" />);

  expect(container.textContent).toContain(
    en.common.discipline.notPlayed.replace("{player}", "Ana").replace("{game}", "League of Legends")
  );
  await press([...container.querySelectorAll("button")].find((node) => node.textContent === en.common.discipline.showAll) ?? null);
  expect(selectScope).toHaveBeenCalledWith("all");
});

it("marks every tournament of the cross-game history with its game", async () => {
  const entry = (id: number, discipline: string) =>
    ({ id, name: `Cup ${id}`, discipline, team: "T", placement: 1, won: 1, lost: 0, draw: 0, maps_won: 2, maps_lost: 0, role: null, encounters: [] }) as unknown as UserTournament;
  await render(<TournamentList tournaments={[entry(1, "lol"), entry(2, "overwatch")]} selectedId={null} onSelect={vi.fn()} showGames />);

  const rows = [...container.querySelectorAll("button[aria-pressed]")].map((node) => node.textContent ?? "");
  expect(rows.find((text) => text.includes("Cup 1"))).toContain("League of Legends");
  expect(rows.find((text) => text.includes("Cup 2"))).toContain("Overwatch");
});

it("marks cross-game matches and hides the MVP filter that needs a game", async () => {
  const encounter = {
    id: 5, name: "A vs B", slot_count: 2, round: 1, best_of: 3, tournament_id: 9, discipline: "lol", status: "completed",
    closeness: null, has_logs: false, result_status: "none", user_team_id: null, tournament: null, stage: null,
    stage_item: null, teams: [], matches: []
  } as unknown as EncounterWithUserStats;
  await render(
    <MatchesTable
      encounters={[encounter]}
      total={1}
      page={1}
      perPage={15}
      selfUserId={7}
      opponents={[]}
      stages={{ group: { w: 0, l: 0 }, playoffs: { w: 0, l: 0 }, finals: { w: 0, l: 0 } }}
      allGames
    />
  );

  expect(container.querySelector("tbody")?.textContent).toContain("League of Legends");
  expect(container.textContent).not.toContain(en.users.matches.filters.mvp1);
});
