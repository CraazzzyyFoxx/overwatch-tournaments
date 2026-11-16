// @vitest-environment happy-dom
//
// The ladder tab belongs to a game that collects its players' career, and only to a player with a linked account in
// it: a player without one, a game that collects none (the read 404s) and a failed read all leave it out.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type * as OverviewModule from "@/app/(site)/users/_views/UserOverviewPage";
import messages from "@/i18n/messages/en.json";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { resolveServer } from "@/test/resolve-server";
import { navigation } from "@/test/url-navigation";

import UserPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const career = vi.hoisted(() => vi.fn());

const tournaments = [{ id: 1, name: "Overwatch Open", discipline: "overwatch" }];
const profile = {
  roles: [],
  tournaments,
  games: [{ discipline: "overwatch", roles: [], tournaments_count: 1, tournaments_won: 0 }],
  tournaments_count: 1,
  tournaments_won: 0,
  characters_count: 0,
  maps_total: 0
};

vi.mock("next/navigation", async () => (await import("@/test/url-navigation")).nextNavigationMock);
vi.mock("@/lib/site/tenant-host", () => ({
  resolveStatsScope: async () => "all",
  resolveServerDisciplineScope: async () => ({ stored: "all", lastGame: null, axis: "all", hostLockedWorkspaceId: null })
}));
vi.mock("@/services/discipline.service", async () => (await import("@/test/discipline-metadata")).disciplineServiceMock);
vi.mock("@/services/user.service", () => ({
  default: {
    getUserByName: async () => ({ id: 108, name: "IngestH0" }),
    getUserProfile: async () => profile,
    getUserCareer: career,
    getUserTournament: async () => null,
    getUserTournamentEncounters: async () => [],
    getUserTournaments: async () => ({ results: [], division_grid_versions: [] }),
    getUserCharacters: async () => null,
    getUserEncounters: async () => ({ results: [], total: 0 }),
    getUserAchievements: async () => [],
    getUserBestTeammates: async () => ({ results: [], total: 0 })
  }
}));
vi.mock("@/app/(site)/users/components/header/UserHeader", () => ({ default: () => null }));
vi.mock("@/app/(site)/users/components/shared/profile-jsonld", () => ({ ProfileJsonLd: () => null }));
vi.mock("@/app/(site)/users/components/overview/OverviewCareerList", () => ({ default: () => null }));
vi.mock("@/app/(site)/users/components/overview/OverviewRecentEncounters", () => ({ default: () => null }));
vi.mock("@/app/(site)/users/components/overview/OverviewAchievementsPreview", () => ({ default: () => null }));
vi.mock("@/app/(site)/users/components/overview/LobbyLeaderboardModal", () => ({ default: () => null }));
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
vi.mock("@/disciplines/registry/profile", () => ({ loadProfileUI: Object.assign(async () => null, { peek: () => undefined }) }));
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
  useWorkspaceStore.setState({ currentWorkspaceId: null, statsScope: "all", hostLockedWorkspaceId: null, gameScope: "all", lastGame: null });
});

afterEach(async () => {
  await act(async () => root.unmount());
  career.mockReset();
});

async function tabs(url: string) {
  navigation.reset(url);
  const search = Object.fromEntries(new URL(url, "http://x").searchParams);
  const page = await resolveServer(
    await UserPage({ params: Promise.resolve({ slug: "IngestH0" }), searchParams: Promise.resolve(search) })
  );
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          {page}
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  return [...container.querySelectorAll('[role="tab"]')].map((tab) => tab.textContent);
}

it("shows the ladder tab for a player with a linked account", async () => {
  career.mockResolvedValue({ user_id: 108, generated_at: "", accounts: [{ social_account_id: 1, handle: "a#1" }] });
  expect(await tabs("/users/IngestH0?discipline=overwatch")).toContain("Ladder");
  expect(career).toHaveBeenCalledWith(108, "overwatch");
});

it("leaves the tab out for a player without an account, and when the read fails", async () => {
  career.mockResolvedValue({ user_id: 108, generated_at: "", accounts: [] });
  expect(await tabs("/users/IngestH0?discipline=overwatch")).not.toContain("Ladder");

  await act(async () => root.unmount());
  root = createRoot(container);
  career.mockRejectedValue(new Error("rank_collection_unsupported"));
  expect(await tabs("/users/IngestH0?discipline=overwatch")).not.toContain("Ladder");
});

it("keeps the tab for a ladder link even without career data, so the link lands on a selected tab", async () => {
  career.mockResolvedValue({ user_id: 108, generated_at: "", accounts: [] });
  expect(await tabs("/users/IngestH0?discipline=overwatch&tab=ladder")).toContain("Ladder");
});
