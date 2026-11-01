// @vitest-environment happy-dom
//
// The mix directory is a directory surface: it shows every game under `?discipline=all` and one game under a
// concrete choice, and the open mixes, the history, the scoreboard and the creation form all follow that one resolved
// choice. Pinned here: the requested game reaches every list read (and is part of its key, so a game's rows never
// serve another's), an invalid choice makes no read at all, creating a mix names its game, and `?view=rating` swaps
// the directory for the full scoreboard.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { navigation } from "@/test/url-navigation";
import { disciplineServiceMock } from "@/test/discipline-metadata";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type {
  CustomGameListItem,
  MixListFilter,
  MixListPage,
  MixMemberStats
} from "@/services/custom-game.service";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const mocks = vi.hoisted(() => ({ list: vi.fn(), stats: vi.fn(), create: vi.fn() }));

vi.mock("next/navigation", async () => (await import("@/test/url-navigation")).nextNavigationMock);
vi.mock("@/services/discipline.service", () => disciplineServiceMock);
vi.mock("@/hooks/usePermissions", () => ({ usePermissions: () => ({ canAccessPermission: () => true }) }));
vi.mock("@/services/custom-game.service", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    customGameService: { list: mocks.list, stats: mocks.stats, create: mocks.create }
  };
});

import BalancerPickupListPage from "./page";

function mix(id: number, discipline: string, name: string): CustomGameListItem {
  return {
    id,
    workspace_id: 1,
    discipline,
    host_user_id: 9,
    co_hosts: [],
    host_display_name: "Host",
    name,
    status: "draft",
    settings: { points_per_win: 0, team_names: {}, workspace_discord_channel_id: null },
    created_at: "2026-01-02T00:00:00Z",
    lobby_count: 1,
    lobbies: [{ lobby_index: 0, selected_variant_index: 0, next_map_id: null, balanced_at: null }],
    self_signup: "closed",
    self_role_edit: false,
    roster_shape: null,
    matches_count: 0,
    last_match_at: null,
    players_count: 0,
    roster_count: 4,
    maps: [],
    maps_count: 0
  } as unknown as CustomGameListItem;
}

const OW_MIX = mix(1, "overwatch", "Overwatch night");
const LOL_MIX = mix(2, "lol", "Rift night");

const mounts: { root: Root; container: HTMLDivElement }[] = [];

async function mountPage(url: string) {
  navigation.reset(url);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mounts.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          <BalancerPickupListPage />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
  return container;
}

async function settle() {
  for (let index = 0; index < 4; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

beforeEach(() => {
  mocks.list
    .mockReset()
    .mockImplementation(async (_workspaceId: number, discipline: string | null, filter: MixListFilter) => ({
      items: [OW_MIX, LOL_MIX].filter(
        (game) =>
          (discipline === null || game.discipline === discipline) &&
          (filter.status === "open") === (game.status === "draft" || game.status === "balanced")
      ),
      next_before_id: null
    }));
  mocks.stats.mockReset().mockResolvedValue({ since: null, members: [], mixes: 0, matches: 0 });
  mocks.create.mockReset().mockResolvedValue(LOL_MIX);
  useWorkspaceStore.setState({
    currentWorkspaceId: 1,
    workspaces: [{ id: 1, name: "OWT", disciplines_enabled: ["overwatch", "lol"] }] as never,
    statsScope: "workspace",
    hostLockedWorkspaceId: null,
    gameScope: "all",
    lastGame: null,
    isLoading: false
  });
  useAuthProfileStore.setState({ status: "anonymous", user: undefined });
});

afterEach(() => {
  for (const { root, container } of mounts.splice(0)) {
    act(() => root.unmount());
    container.remove();
  }
  document.body.innerHTML = "";
});

const rows = (container: ParentNode) => [...container.querySelectorAll("li a")].map((link) => link.textContent ?? "");
const lists = () => mocks.list.mock.calls.map((call) => [call[0], call[1], call[2].status]);

describe("mix directory browsing game", () => {
  it("lists every game under all games and marks each row's game", async () => {
    const container = await mountPage("/balancer/mix?discipline=all");

    expect(lists()).toEqual([
      [1, null, "open"],
      [1, null, "history"]
    ]);
    expect(mocks.stats.mock.calls.map((call) => call[2])).toEqual([undefined]);
    const text = rows(container).join("|");
    expect(text).toContain("Overwatch night");
    expect(text).toContain("Rift night");
    expect(text).toContain("League of Legends");
  });

  it("narrows the list and the scoreboard to the chosen game", async () => {
    const container = await mountPage("/balancer/mix?discipline=lol");

    expect(lists()).toEqual([
      [1, "lol", "open"],
      [1, "lol", "history"]
    ]);
    expect(mocks.stats.mock.calls.map((call) => call[2])).toEqual(["lol"]);
    expect(rows(container).join("|")).toContain("Rift night");
    expect(rows(container).join("|")).not.toContain("Overwatch night");
  });

  it("never shows the previous game's rows for the next one", async () => {
    const pending = Promise.withResolvers<MixListPage>();
    const container = await mountPage("/balancer/mix?discipline=overwatch");
    expect(rows(container).join("|")).toContain("Overwatch night");

    mocks.list.mockImplementationOnce(() => pending.promise);
    await act(async () => navigation.push("/balancer/mix?discipline=lol"));
    await settle();

    // The LoL read is still in flight: the OW rows must not stand in for it.
    expect(rows(container).join("|")).not.toContain("Overwatch night");
    expect(container.querySelector('[role="status"]')?.textContent).toContain("Loading");

    await act(async () => pending.resolve({ items: [LOL_MIX], next_before_id: null }));
    await settle();
    expect(rows(container).join("|")).toContain("Rift night");
  });

  it("makes no read for an invalid game and names it", async () => {
    const container = await mountPage("/balancer/mix?discipline=chess");

    expect(mocks.list).not.toHaveBeenCalled();
    expect(mocks.stats).not.toHaveBeenCalled();
    expect(container.textContent).toContain("chess");
    expect(rows(container)).toEqual([]);
  });

  it("creates a mix for the directory's game", async () => {
    const container = await mountPage("/balancer/mix?discipline=lol");

    await act(async () => {
      [...container.querySelectorAll("button")].find((button) => button.textContent?.includes("Create mix"))?.click();
    });
    await settle();
    const form = document.body.querySelector("form");
    expect(form).not.toBeNull();
    expect(document.body.querySelector("#pickup-discipline")?.textContent).toBe("League of Legends");
    await act(async () => {
      form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    await settle();

    expect(mocks.create).toHaveBeenCalledWith(1, "lol", expect.any(String), null);
  });

  it("narrows to the saved game scope without writing the URL, and marks no row", async () => {
    useWorkspaceStore.setState({ gameScope: "lol" });
    const container = await mountPage("/balancer/mix");

    expect(lists()).toEqual([
      [1, "lol", "open"],
      [1, "lol", "history"]
    ]);
    expect(navigation.replaces).toEqual([]);
    expect(rows(container).join("|")).toContain("Rift night");
    expect(rows(container).join("|")).not.toContain("League of Legends");
  });

  it("swaps the directory for the full scoreboard under ?view=rating", async () => {
    const aria: MixMemberStats = {
      workspace_member_id: 3,
      display_name: "Aria",
      display: { name: "Aria", tag: null, canonical: null, snapshot: null },
      identity: null,
      games: 9,
      wins: 6,
      losses: 3,
      draws: 0,
      win_rate: 6 / 9,
      streak: 2,
      last_played_at: null,
      player_id: 30,
      form: [],
      by_role: null
    };
    mocks.stats.mockResolvedValue({ since: null, members: [aria], mixes: 2, matches: 9 });
    const container = await mountPage("/balancer/mix?view=rating");

    expect(container.querySelector('[aria-current="page"]')?.textContent).toBe("Leaderboard");
    expect([...container.querySelectorAll("tbody tr")].map((row) => row.textContent)).toEqual([
      expect.stringContaining("Aria")
    ]);
    expect(container.querySelector('input[placeholder="Mix or host"]')).toBeNull();
  });
});

describe("mix directory under all communities", () => {
  it("reads the listed and the viewer's own communities, not every one a superuser can administer", async () => {
    const listed = { id: 1, name: "Listed", disciplines_enabled: ["overwatch"], is_hidden: false, verification_status: "verified" };
    const mine = { id: 2, name: "Mine", disciplines_enabled: ["overwatch"], is_hidden: true, verification_status: "unverified" };
    // Hidden or unverified and not a member: reachable only through superuser powers.
    const unlisted = Array.from({ length: 200 }, (_, index) => ({
      id: 100 + index,
      name: `Unlisted ${index}`,
      disciplines_enabled: ["overwatch"],
      is_hidden: index % 2 === 0,
      verification_status: index % 2 === 0 ? "verified" : "unverified"
    }));
    useWorkspaceStore.setState({ statsScope: "all", workspaces: [listed, mine, ...unlisted] as never });
    useAuthProfileStore.setState({
      status: "authenticated",
      user: {
        username: "root",
        roles: [],
        permissions: [],
        denies: [],
        isSuperuser: true,
        workspaces: [{ workspace_id: 2, slug: "mine", roles: ["owner"], permissions: [] }],
        linkedPlayers: []
      }
    });
    mocks.list.mockResolvedValue({ items: [], next_before_id: null });

    await mountPage("/balancer/mix?discipline=all");

    // One open read, one history page and one scoreboard per community: O(listed + own), not O(every workspace).
    expect(lists()).toEqual([
      [1, null, "open"],
      [2, null, "open"],
      [1, null, "history"],
      [2, null, "history"]
    ]);
    expect(mocks.stats.mock.calls.map((call) => call[0])).toEqual([1, 2]);
  });
});
