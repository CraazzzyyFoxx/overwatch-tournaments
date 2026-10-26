// @vitest-environment happy-dom
//
// The admin tournaments list spans every game until its "Game" chip (`?discipline=`) narrows it: an "Игра" column
// with no game filtered; under a game the server filters and the column is gone.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { navigation } from "@/test/url-navigation";
import type { Tournament } from "@/types/tournament.types";

import { TournamentsBrowser } from "./TournamentsBrowser";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const { getAll, viewport } = vi.hoisted(() => ({ getAll: vi.fn(), viewport: { mobile: false } }));

vi.mock("next/navigation", async () => (await import("@/test/url-navigation")).nextNavigationMock);
vi.mock("@/services/discipline.service", async () => (await import("@/test/discipline-metadata")).disciplineServiceMock);
vi.mock("@/services/tournament.service", () => ({ default: { getAll } }));
vi.mock("@/services/admin.service", () => ({ default: { deleteTournament: vi.fn() } }));
vi.mock("@/hooks/usePermissions", () => ({ usePermissions: () => ({ canAccessPermission: () => true }) }));
vi.mock("@/hooks/useMobile", () => ({ useIsMobile: () => viewport.mobile }));

function tournament(id: number, discipline: string, name: string): Tournament {
  return {
    id,
    name,
    discipline,
    is_league: false,
    is_hidden: false,
    is_finished: false,
    status: "registration",
    start_date: new Date("2026-02-01T00:00:00Z"),
    end_date: new Date("2026-02-08T00:00:00Z"),
    stages: []
  } as unknown as Tournament;
}

const POOL = [tournament(1, "overwatch", "Spring Cup"), tournament(2, "lol", "Rift Cup")];
/** Another community's tournament: a read without a workspace returns it too. */
const ELSEWHERE = tournament(3, "overwatch", "Other Community Cup");

let root: Root;
let container: HTMLDivElement;

async function settle() {
  for (let turn = 0; turn < 6; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount(url: string) {
  navigation.reset(url);
  await act(async () => {
    root.render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          <TournamentsBrowser />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
}

const headers = () => [...container.querySelectorAll("th")].map((cell) => cell.textContent?.trim() ?? "");
const rowText = (name: string) =>
  [...container.querySelectorAll("tbody tr")].map((row) => row.textContent ?? "").find((text) => text.includes(name));

async function click(element: Element | null | undefined) {
  await act(async () => element?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}
const commandItems = () => [...document.querySelectorAll('[cmdk-item=""]')];
// The table draws each tournament's stages, so this list (unlike the pickers) asks for them.
const ENTITIES = ["stages", "participants_count"];

beforeEach(() => {
  viewport.mobile = false;
  getAll.mockReset().mockImplementation(async (_isLeague: unknown, workspace?: number | null, discipline?: string | null) => {
    const results = (workspace === 1 ? POOL : [...POOL, ELSEWHERE]).filter(
      (entry) => !discipline || entry.discipline === discipline
    );
    return { results, total: results.length, page: 1, per_page: -1 };
  });
  useWorkspaceStore.setState({
    currentWorkspaceId: 1,
    workspaces: [{ id: 1, name: "OWT", disciplines_enabled: ["overwatch", "lol"] }] as never,
    statsScope: "workspace",
    hostLockedWorkspaceId: null,
    gameScope: "all",
    lastGame: null
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("admin tournaments list across games", () => {
  it("lists every game's tournaments with no game filtered, whatever the site's saved scope, with a Game column", async () => {
    useWorkspaceStore.setState({ gameScope: "lol", lastGame: "lol" });
    await mount("/admin/tournaments");

    expect(getAll).toHaveBeenCalledWith(null, 1, null, ENTITIES);
    expect(headers().some((text) => text.includes(en.common.discipline.column))).toBe(true);
    expect(rowText("Rift Cup")).toContain("League of Legends");
    expect(rowText("Spring Cup")).toContain("Overwatch");
  });

  it("asks the server for one game's tournaments under a game, without the column", async () => {
    await mount("/admin/tournaments?discipline=lol");

    expect(getAll).toHaveBeenLastCalledWith(null, 1, "lol", ENTITIES);
    expect(headers().some((text) => text.includes(en.common.discipline.column))).toBe(false);
    expect(rowText("Rift Cup")).toBeDefined();
    expect(rowText("Spring Cup")).toBeUndefined();
  });

  it("offers the Game chip first, and a picked game asks the server for that game's tournaments", async () => {
    await mount("/admin/tournaments?status=registration");

    await click(container.querySelector(`button[aria-label="${en.kit.actions.addFilter}"]`));
    expect(commandItems()[0]?.textContent?.trim()).toBe(en.common.discipline.column);
    await click(commandItems()[0]);
    // An option reads as the game's mark then its name.
    await click(commandItems().find((item) => item.textContent?.endsWith("League of Legends")));
    await settle();

    expect(navigation.current()).toBe("/admin/tournaments?status=registration&discipline=lol");
    expect(getAll).toHaveBeenLastCalledWith(null, 1, "lol", ENTITIES);
    expect(rowText("Spring Cup")).toBeUndefined();
  });

  it("removing the Game chip lists every game again", async () => {
    await mount("/admin/tournaments?discipline=lol");

    await click(container.querySelector('button[aria-label="Remove filter Game: League of Legends"]'));
    await settle();

    expect(navigation.current()).toBe("/admin/tournaments");
    expect(getAll).toHaveBeenLastCalledWith(null, 1, null, ENTITIES);
    expect(rowText("Spring Cup")).toBeDefined();
  });

  it("reads nothing for an unknown game and leaves its URL as typed, then lists every game on request", async () => {
    await mount("/admin/tournaments?discipline=starcraft");

    expect(getAll).not.toHaveBeenCalled();
    expect(navigation.current()).toBe("/admin/tournaments?discipline=starcraft");

    const showAll = [...container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === en.common.discipline.showAll
    );
    await act(async () => showAll?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await settle();

    expect(navigation.current()).toBe("/admin/tournaments");
    expect(getAll).toHaveBeenCalledWith(null, 1, null, ENTITIES);
    expect(rowText("Rift Cup")).toContain("League of Legends");
  });

  it("names each phone card's game under all games, whatever column order the user saved before the Game column", async () => {
    // A desktop column order saved before the Game column existed: the table appends it after these.
    const stored = new Map([["admin-table:/admin/tournaments:order", JSON.stringify(["name", "status", "start_date", "stages"])]]);
    // Node's own `localStorage` throws without `--localstorage-file` and happy-dom does not shadow it.
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: (key: string) => stored.get(key) ?? null,
        setItem: (key: string, value: string) => void stored.set(key, value),
        removeItem: (key: string) => void stored.delete(key)
      }
    });
    viewport.mobile = true;
    await mount("/admin/tournaments");

    const cards = [...container.querySelectorAll("ul[aria-label='Rows'] > li")].map((card) => card.textContent ?? "");
    const rift = cards.find((text) => text.includes("Rift Cup"));
    expect(rift).toContain("League of Legends");
    expect(rift).toContain(en.common.statusBadge.registration);
    expect(cards.find((text) => text.includes("Spring Cup"))).toContain("Overwatch");
  });

  it("reads nothing on a first visit until the community is known, then reads that community's list once", async () => {
    useWorkspaceStore.setState({ currentWorkspaceId: null });
    await mount("/admin/tournaments");
    expect(getAll).not.toHaveBeenCalled();

    await act(async () => useWorkspaceStore.setState({ currentWorkspaceId: 1 }));
    await settle();

    expect(getAll.mock.calls).toEqual([[null, 1, null, ENTITIES]]);
    expect(rowText("Spring Cup")).toBeDefined();
    expect(rowText("Other Community Cup")).toBeUndefined();
  });
});
