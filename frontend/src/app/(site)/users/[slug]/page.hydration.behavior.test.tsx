// @vitest-environment happy-dom
//
// The profile's blocks stream in after the site header, and by the time one hydrates the browser may hold some of the
// games' data already: a block may have read its game's metadata. A block's first browser render must still be the
// server's. Under "all games" the overview's role split (named and painted from its game's metadata) hydrates the
// server's markup of the page, inside its layout, into such a browser without a mismatch.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";

import type * as OverviewModule from "@/app/(site)/users/_views/UserOverviewPage";
import messages from "@/i18n/messages/en.json";
import { disciplineQueryKeys } from "@/lib/site/discipline-query-keys";
import { OW_METADATA } from "@/test/discipline-metadata";
import { resolveServer } from "@/test/resolve-server";
import { navigation } from "@/test/url-navigation";

import SiteLayout from "../../layout";
import UserPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const { profile, dossier } = vi.hoisted(() => {
  const support = { dimension: "player_role", role: "support" };
  // A player of both games, one tournament each: Overwatch (area order first) is the overview's game.
  const crossGame = {
    tournaments: [
      { id: 1, name: "Overwatch Open", discipline: "overwatch" },
      { id: 2, name: "Rift Clash", discipline: "lol" }
    ],
    games: [
      {
        discipline: "overwatch",
        roles: [{ role: support, division: 5 }],
        tournaments_count: 1,
        tournaments_won: 0
      },
      { discipline: "lol", roles: [], tournaments_count: 1, tournaments_won: 0 }
    ],
    roles: [],
    tournaments_count: 2,
    tournaments_won: 0,
    characters_count: 0,
    maps_total: 0
  };
  return {
    // The overview's last tournament, played as Support, in community 3: its role is drawn from that community's
    // Overwatch metadata, which no other block reads.
    dossier: {
      id: 1,
      name: "Overwatch Open",
      workspace_id: 3,
      discipline: "overwatch",
      division: 5,
      division_grid_version: null,
      role: support,
      group_placement: 0,
      playoff_placement: 0,
      maps_won: 0,
      maps: 0,
      playtime: 0,
      stats: {}
    },
    profile: (game: string | null) =>
      game === null
        ? crossGame
        : {
            ...crossGame,
            roles: [{ role: support, maps: 0, maps_won: 0, tournaments: 1, division: 5, division_grid_version: null }]
          }
  };
});

// `vi.mock` factories run before this file's imports, so the modules they hand out are loaded inside them.
vi.mock("next/navigation", async () => (await import("@/test/url-navigation")).nextNavigationMock);
vi.mock("next/headers", () => ({ headers: async () => new Headers(), cookies: async () => ({ get: () => undefined }) }));
// A visitor with no saved game, across communities.
vi.mock("@/lib/site/tenant-host", () => ({
  resolveStatsScope: async () => "all",
  resolveServerDisciplineScope: async () => ({ stored: "all", lastGame: null, axis: "all", hostLockedWorkspaceId: null })
}));
vi.mock("@/services/discipline.service", async () => (await import("@/test/discipline-metadata")).disciplineServiceMock);
vi.mock("@/services/user.service", () => ({
  default: {
    getUserByName: async () => ({ id: 108, name: "IngestH0" }),
    getUserProfile: async (_id: number, game: string | null) => profile(game),
    getUserTournament: async () => dossier,
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
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
vi.mock("@/disciplines/registry/profile", () => ({ loadProfileUI: Object.assign(async () => null, { peek: () => undefined }) }));
// The overview awaits its sections, as the RSC renderer does (`resolveServer` only awaits async components).
vi.mock("@/app/(site)/users/_views/UserOverviewPage", async (importOriginal) => {
  const actual = await importOriginal<typeof OverviewModule>();
  return { ...actual, default: async (props: Parameters<typeof actual.default>[0]) => actual.default(props) };
});
// The layout's chrome has its own suites.
vi.mock("@/components/Header", () => ({ default: () => null }));
vi.mock("@/components/Footer", () => ({ Footer: () => null }));
vi.mock("@/components/notifications/FloatStack", () => ({ FloatStack: () => null }));
vi.mock("@/services/notification.service", () => ({ default: { activeAnnouncements: async () => [] } }));
vi.mock("@/i18n/ZoneIntlProvider", () => ({ default: ({ children }: { children: ReactNode }) => children }));

let hydrated: Root | undefined;
let host: HTMLElement | undefined;

afterEach(async () => {
  await act(async () => hydrated?.unmount());
  host?.remove();
  hydrated = host = undefined;
});

async function settle(turns = 8) {
  for (let turn = 0; turn < turns; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

/**
 * The server's markup of the profile under all games, inside the site layout, hydrated into a browser whose cache
 * `prewarm` filled; the same tree on both sides, only the query client differs, as one request's and the browser's do.
 */
async function hydrateProfile(prewarm: (client: QueryClient) => void) {
  navigation.reset("/users/IngestH0");
  const page = await resolveServer(
    <SiteLayout>
      <UserPage params={Promise.resolve({ slug: "IngestH0" })} searchParams={Promise.resolve({})} />
    </SiteLayout>
  );
  const tree = (queryClient: QueryClient) => (
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      <QueryClientProvider client={queryClient}>{page}</QueryClientProvider>
    </NextIntlClientProvider>
  );
  const html = renderToString(tree(new QueryClient()));

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  prewarm(client);
  host = document.body.appendChild(document.createElement("div"));
  host.innerHTML = html;
  const recoverable: unknown[] = [];
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  await act(async () => {
    hydrated = hydrateRoot(host as HTMLElement, tree(client), {
      onRecoverableError: (error) => void recoverable.push(error)
    });
  });
  await settle();
  const mismatches = errors.mock.calls.filter((call) => String(call[0]).toLowerCase().includes("hydrat"));
  errors.mockRestore();
  return { html, recoverable, mismatches };
}

it("names and paints the role split's roles on the server, and hydrates it where a block read the game's metadata", async () => {
  const { html, recoverable, mismatches } = await hydrateProfile((client) =>
    client.setQueryData(disciplineQueryKeys.metadata("all", "overwatch"), OW_METADATA)
  );

  expect(recoverable.map(String)).toEqual([]);
  expect(mismatches).toEqual([]);
  expect(html).toContain(">Support<");
  expect(html).toContain("#10b981");
  expect(host?.textContent).toContain("Support");
});

it("names the last tournament's role on the server, from its own community's metadata, and hydrates it", async () => {
  const { html, recoverable, mismatches } = await hydrateProfile((client) =>
    client.setQueryData(disciplineQueryKeys.metadata(3, "overwatch"), OW_METADATA)
  );

  expect(recoverable.map(String)).toEqual([]);
  expect(mismatches).toEqual([]);
  const server = document.createElement("div");
  server.innerHTML = html;
  const card = [...server.querySelectorAll('[data-ui="card"]')].find((node) => node.textContent?.includes("Overwatch Open"));
  expect(card?.querySelector('[title="Support"]')).toBeTruthy();
  expect(card?.textContent).toContain("Support");
  expect(html).not.toContain("Unknown role");
});
