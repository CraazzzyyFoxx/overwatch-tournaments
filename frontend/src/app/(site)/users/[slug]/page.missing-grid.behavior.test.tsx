// A player's profile in a game with no division grid on the viewed axis is refused by the server (422
// `division_grid_required`) for the profile and every tab alike. The page names the missing grid in their place —
// across communities as a choice of community, on a workspace as that workspace's missing grid — and any other
// failure still reaches the route's error boundary. Under "all games" a per-game tab reads its game's own profile and
// is refused the same way: the notice then stands under the game tabs.
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { ApiError } from "@/lib/api/error";
import type { PageGame, WorkspaceAxis } from "@/lib/site/discipline-scope";
import type { StatsScope } from "@/lib/site/stats-scope";
import { resolveServer } from "@/test/resolve-server";

import UserPage from "./page";

const { view, getUserProfile } = vi.hoisted(() => ({
  view: { scope: "all" as StatsScope, axis: "all" as WorkspaceAxis, game: { kind: "all" } as PageGame },
  getUserProfile: vi.fn()
}));

vi.mock("@/lib/site/tenant-host", () => ({ resolveStatsScope: async () => view.scope }));
vi.mock("@/lib/site/discipline-server", () => ({
  resolveServerPageGame: async () => ({
    init: {
      stored: "all",
      lastGame: null,
      axis: view.axis,
      hostLockedWorkspaceId: null,
      disciplines: [
        { code: "overwatch", name: "Overwatch", short_name: "OW", icon: null, enabled: true, capabilities: { native_rank_collection: false } },
        { code: "lol", name: "League of Legends", short_name: "LoL", icon: null, enabled: true, capabilities: { native_rank_collection: false } }
      ]
    },
    resolution: { game: view.game, pill: { kind: "all" }, tabs: false, scope: "all" }
  })
}));
vi.mock("@/services/user.service", () => ({
  default: { getUserByName: async () => ({ id: 7, name: "Faker" }), getUserProfile }
}));
// The fixture loads inside the factory: `vi.mock` factories run before this file's imports.
vi.mock("@/services/discipline.service", async () => (await import("@/test/discipline-metadata")).disciplineServiceMock);
// The profile around a per-game tab has its own suites: only the tab's own game read is exercised here.
vi.mock("@/app/(site)/users/components/header/UserHeader", () => ({ default: () => null }));
vi.mock("@/app/(site)/users/components/shared/profile-jsonld", () => ({ ProfileJsonLd: () => null }));
vi.mock("@/app/(site)/users/components/shared/ProfileGameTabs", () => ({ default: () => "[game tabs]" }));
vi.mock("@/app/(site)/users/components/shared/ProfileGameData", () => ({
  default: ({ children }: { children: ReactNode }) => children
}));
vi.mock("@/app/(site)/users/_views/UserOverviewPage", () => ({
  default: () => "[overview]",
  UserOverviewPageSkeleton: () => null
}));
vi.mock("@/app/(site)/users/components/tabs/UserTabsClient", async () => {
  const { Tabs } = await import("@/components/ui/tabs");
  return {
    default: ({ activeTab, children }: { activeTab: string; children: ReactNode }) => (
      <Tabs value={activeTab}>{children}</Tabs>
    )
  };
});

const REFUSAL = new ApiError(422, [
  { msg: "division_grid_required: 'lol' needs a division grid of its own with tiers", code: "unprocessable" }
]);

const renderProfile = async () =>
  renderToStaticMarkup(
    await resolveServer(
      await UserPage({
        params: Promise.resolve({ slug: "Faker" }),
        searchParams: Promise.resolve({ discipline: "lol" })
      })
    )
  );

beforeEach(() => {
  view.game = { kind: "game", code: "lol", source: "url" };
  getUserProfile.mockReset().mockRejectedValue(REFUSAL);
});

it("tells the all-communities view to choose a community", async () => {
  view.scope = "all";
  view.axis = "all";

  const html = await renderProfile();

  expect(html).toContain('role="alert"');
  expect(html).toContain(en.common.discipline.gridMissingAcross.replaceAll("{game}", "League of Legends"));
  expect(html).not.toContain("division_grid_required");
  // Nothing of the profile is drawn around it: no header, no tabs.
  expect(html).not.toContain('role="tablist"');
});

it("names the workspace's missing grid on a workspace", async () => {
  view.scope = "workspace";
  view.axis = 1;

  const html = await renderProfile();

  expect(html).toContain(en.common.discipline.gridMissing);
  expect(html).not.toContain(en.common.discipline.gridMissingAcross.split("{game}")[1]);
});

it("leaves any other failure to the route's error boundary", async () => {
  getUserProfile.mockReset().mockRejectedValue(new ApiError(500, [{ msg: "boom", code: "error" }]));

  await expect(renderProfile()).rejects.toBeInstanceOf(ApiError);
});

it("names a per-game tab's missing grid under its game tabs when the page shows every game", async () => {
  view.scope = "all";
  view.axis = "all";
  view.game = { kind: "all" };
  // The cross-game profile reads no grid (R13); the tab's own game (the player's main one, LoL) is refused.
  getUserProfile.mockReset().mockImplementation(async (_id: number, game: string | null) => {
    if (game !== null) throw REFUSAL;
    return {
      tournaments: [{ id: 1, discipline: "lol" }],
      games: [
        { discipline: "lol", roles: [], tournaments_count: 2, tournaments_won: 0 },
        { discipline: "overwatch", roles: [], tournaments_count: 1, tournaments_won: 0 }
      ],
      tournaments_count: 3,
      characters_count: 0,
      maps_total: 0
    };
  });

  const html = await renderProfile();

  expect(getUserProfile).toHaveBeenCalledWith(7, "lol", "all");
  expect(html).toContain("[game tabs]");
  expect(html).toContain(en.common.discipline.gridMissingAcross.replaceAll("{game}", "League of Legends"));
  expect(html).not.toContain("[overview]");
});
