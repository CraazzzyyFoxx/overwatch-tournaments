// @vitest-environment happy-dom
//
// A pinned tournament (`?tournamentId=`, `?achievementTournamentId=`, `?selectedTournamentId=`) is one game's: when
// the profile changes game — a per-game tab under "all games", or a game picked in the scope pill — the pin goes with
// the game, and the next game's blocks read their own tournaments (spec §6.2, ruling R5).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type * as OverviewModule from "@/app/(site)/users/_views/UserOverviewPage";
import messages from "@/i18n/messages/en.json";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { PillPick } from "@/test/pill-pick";
import { resolveServer } from "@/test/resolve-server";
import { navigation } from "@/test/url-navigation";

import UserPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const { profile, dossier } = vi.hoisted(() => {
  const tournaments = [
    { id: 1, name: "Overwatch Open", discipline: "overwatch" },
    { id: 2, name: "Rift Clash", discipline: "lol" }
  ];
  const games = [
    { discipline: "overwatch", roles: [], tournaments_count: 1, tournaments_won: 0 },
    { discipline: "lol", roles: [], tournaments_count: 1, tournaments_won: 0 }
  ];
  const base = { roles: [], tournaments_won: 0, characters_count: 0, maps_total: 0 };
  return {
    // A player of both games, one tournament each; a game's own profile lists that game's tournament only.
    profile: (game: string | null) =>
      game === null
        ? { ...base, tournaments, games, tournaments_count: 2 }
        : {
            ...base,
            tournaments: tournaments.filter((entry) => entry.discipline === game),
            games: [],
            tournaments_count: 1
          },
    dossier: (id: number) => {
      const entry = tournaments.find((tournament) => tournament.id === id);
      return entry
        ? {
            id,
            name: entry.name,
            workspace_id: 3,
            discipline: entry.discipline,
            division: 5,
            division_grid_version: null,
            role: null,
            group_placement: 0,
            playoff_placement: 0,
            maps_won: 0,
            maps: 0,
            playtime: 0,
            stats: {}
          }
        : null;
    }
  };
});

// `vi.mock` factories run before this file's imports, so the modules they hand out are loaded inside them.
vi.mock("next/navigation", async () => (await import("@/test/url-navigation")).nextNavigationMock);
// No saved game, across communities; the last game is the one a pick saved (the cookie the next request carries).
vi.mock("@/lib/site/tenant-host", async () => {
  const { useWorkspaceStore: store } = await import("@/stores/workspace.store");
  return {
    resolveStatsScope: async () => "all",
    resolveServerDisciplineScope: async () => ({
      stored: "all",
      lastGame: store.getState().lastGame,
      axis: "all",
      hostLockedWorkspaceId: null
    })
  };
});
vi.mock("@/services/discipline.service", async () => (await import("@/test/discipline-metadata")).disciplineServiceMock);
vi.mock("@/services/user.service", () => ({
  default: {
    getUserByName: async () => ({ id: 108, name: "IngestH0" }),
    getUserProfile: async (_id: number, game: string | null) => profile(game),
    getUserTournament: async (_id: number, tournamentId: number) => dossier(tournamentId),
    getUserTournamentEncounters: async () => [],
    getUserTournaments: async () => ({ results: [], division_grid_versions: [] }),
    getUserCharacters: async () => null,
    getUserMaps: async () => null,
    getUserEncounters: async () => ({ results: [], total: 0 }),
    getUserAchievements: async () => [],
    getUserBestTeammates: async () => ({ results: [], total: 0 })
  }
}));
// The rest of the page has its own suites.
vi.mock("@/app/(site)/users/components/header/UserHeader", () => ({ default: () => null }));
vi.mock("@/app/(site)/users/components/shared/profile-jsonld", () => ({ ProfileJsonLd: () => null }));
vi.mock("@/app/(site)/users/components/overview/OverviewCareerList", () => ({ default: () => null }));
vi.mock("@/app/(site)/users/components/overview/OverviewRecentEncounters", () => ({ default: () => null }));
vi.mock("@/app/(site)/users/components/overview/OverviewAchievementsPreview", () => ({ default: () => null }));
vi.mock("@/app/(site)/users/components/overview/LobbyLeaderboardModal", () => ({ default: () => null }));
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
vi.mock("@/disciplines/registry/profile", () => ({ loadProfileUI: Object.assign(async () => null, { peek: () => undefined }) }));
// The overview awaits its sections, as the RSC renderer does (`resolveServer` only awaits async components).
vi.mock("@/app/(site)/users/_views/UserOverviewPage", async (importOriginal) => {
  const actual = await importOriginal<typeof OverviewModule>();
  return { ...actual, default: async (props: Parameters<typeof actual.default>[0]) => actual.default(props) };
});

let root: Root;
let container: HTMLElement;

beforeEach(() => {
  document.body.innerHTML = "";
  container = document.body.appendChild(document.createElement("div"));
  root = createRoot(container);
  useWorkspaceStore.setState({
    currentWorkspaceId: null,
    statsScope: "all",
    hostLockedWorkspaceId: null,
    gameScope: "all",
    lastGame: null
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
});

const query = () => new URL(navigation.current(), "http://x").searchParams;

/** The server's render of the profile for the current URL and cookies, mounted in the browser. */
async function renderProfile(extra?: ReactNode) {
  const page = await resolveServer(
    await UserPage({
      params: Promise.resolve({ slug: "IngestH0" }),
      searchParams: Promise.resolve(Object.fromEntries(query()))
    })
  );
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          {page}
          {extra}
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
}

async function press(element: Element | null | undefined) {
  expect(element).toBeTruthy();
  await act(async () => {
    element!.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    element!.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    (element as HTMLElement).click();
  });
}

it("drops a pinned tournament when a per-game tab picks another game, whose overview reads its own", async () => {
  navigation.reset("/users/IngestH0?tournamentId=1");
  await renderProfile();
  expect(container.textContent).toContain("Overwatch Open");

  const league = [...container.querySelectorAll('[role="tab"]')].find((tab) =>
    tab.textContent?.endsWith("League of Legends")
  );
  await press(league);

  expect(useWorkspaceStore.getState().lastGame).toBe("lol");
  expect(query().has("tournamentId")).toBe(false);
  await renderProfile();
  expect(container.textContent).toContain("Rift Clash");
  expect(container.textContent).not.toContain("Overwatch Open");
});

it("drops the achievements' tournament filter when the scope pill picks a game", async () => {
  navigation.reset("/users/IngestH0?tab=achievements&achievementTournamentId=t-1");
  await renderProfile(<PillPick code="lol" />);

  await press(container.querySelector('[data-pill-pick="lol"]'));

  expect(query().get("discipline")).toBe("lol");
  expect(query().get("tab")).toBe("achievements");
  expect(query().has("achievementTournamentId")).toBe(false);
});
