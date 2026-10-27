// @vitest-environment happy-dom
//
// The analytics page host (P7 §7 `analytics` slot): the selected tournament is the owner (its workspace and game,
// never the browsing filter); a game without the analytics capability gets an explicit unsupported state, loads no
// module and reads nothing from analytics; the picker offers only tournaments of games that have a board.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, lazy } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import type { AnalyticsSlot, DisciplineUI, SlotProps } from "@/disciplines/types";
import { disciplineServiceMock } from "@/test/discipline-metadata";
import type { Tournament } from "@/types/tournament.types";

import AnalyticsClient from "./AnalyticsClient";

const nav = vi.hoisted(() => ({ params: new URLSearchParams(), replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: nav.push }),
  usePathname: () => "/tournaments/analytics",
  useSearchParams: () => nav.params
}));

const OW_WORKSPACE = 7;
function tournament(id: number, name: string, discipline: string): Tournament {
  return {
    id,
    name,
    discipline,
    workspace_id: OW_WORKSPACE,
    status: "completed",
    start_date: "2026-01-01",
    end_date: "2026-01-02",
    is_league: false,
    team_formation: null,
    stages: []
  } as unknown as Tournament;
}
// Newest first, as the list reads them: the newest is a League event.
const LOL_CUP = tournament(30, "League Cup", "lol");
const OW_CUP = tournament(20, "Overwatch Cup", "overwatch");
const OW_OPEN = tournament(10, "Overwatch Open", "overwatch");
const ALL = [LOL_CUP, OW_CUP, OW_OPEN];

const tournaments = vi.hoisted(() => ({ getAll: vi.fn(), getPublicOverview: vi.fn() }));
vi.mock("@/services/tournament.service", () => ({ default: tournaments }));
// The scope's game list can be overridden per case (e.g. Overwatch disabled); metadata stays the shared fixture.
const games = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/services/discipline.service", () => ({
  default: { list: games.list, metadata: disciplineServiceMock.default.metadata }
}));
const analytics = vi.hoisted(() => ({ getAlgorithms: vi.fn(), getAnalytics: vi.fn() }));
vi.mock("@/services/analytics.service", () => ({ default: analytics }));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    hasPermission: () => false,
    canAccessPermission: (_permission: string, workspaceId: number) => workspaceId === OW_WORKSPACE
  })
}));

// The registry's loader, replaced by a module whose board shows what the host handed it.
const seen = vi.hoisted(() => ({ props: null as unknown }));
const registry = vi.hoisted(() => ({ loadAnalyticsUI: Object.assign(vi.fn(), { peek: () => undefined }) }));
vi.mock("@/disciplines/registry/analytics", () => registry);
const BOARD: DisciplineUI<AnalyticsSlot> = {
  code: "overwatch",
  slots: {
    analytics: lazy(async () => ({
      default: (props: SlotProps["analytics"]) => {
        seen.props = props;
        return (
          <>
            {props.hero({ counts: { teams: 2, players: 3 }, controls: <span>Linear</span> })}
            <p data-testid="board">{`board of ${props.tournamentId}`}</p>
          </>
        );
      }
    }))
  }
};

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLElement;

async function settle() {
  for (let turn = 0; turn < 8; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function render(query: string) {
  nav.params = new URLSearchParams(query);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root = createRoot(container);
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={messages}>
          <AnalyticsClient scope="all" />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  for (const fn of [nav.replace, nav.push, ...Object.values(tournaments), ...Object.values(analytics)]) fn.mockReset();
  registry.loadAnalyticsUI.mockReset().mockImplementation(async (code: string) => (code === "overwatch" ? BOARD : null));
  seen.props = null;
  games.list.mockReset().mockImplementation(disciplineServiceMock.default.list);
  tournaments.getAll.mockResolvedValue({ results: ALL, total: ALL.length, page: 1, per_page: -1 });
  tournaments.getPublicOverview.mockImplementation(async (id: number) => ALL.find((item) => item.id === id));
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container.remove();
});

describe("tournament analytics host", () => {
  it("opens the newest tournament whose game has an analytics board, not the newest tournament", async () => {
    await render("");

    expect(nav.replace).toHaveBeenCalledWith("/tournaments/analytics?tournamentId=20");
    expect(tournaments.getAll).toHaveBeenCalledWith(null, "all", null, ["stages", "participants_count"]);
  });

  it("offers no tournament of a disabled game: a League-only workspace keeps its old Overwatch events unopened", async () => {
    const installed = await disciplineServiceMock.default.list();
    games.list.mockResolvedValue(
      installed.map((game) => (game.code === "overwatch" ? { ...game, enabled: false } : game))
    );

    await render("");

    expect(nav.replace).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Choose parameters");
    expect(registry.loadAnalyticsUI).not.toHaveBeenCalled();

    // An explicitly opened historical owner is still that tournament's analytics.
    act(() => root?.unmount());
    await render("tournamentId=20");
    expect(container.querySelector("[data-testid=board]")?.textContent).toBe("board of 20");
  });

  it("says a League tournament has no analytics, loads no module and reads nothing from analytics", async () => {
    await render("tournamentId=30");

    expect(container.textContent).toContain("Analytics is not available for League of Legends");
    expect(container.textContent).toContain("League Cup");
    expect(registry.loadAnalyticsUI).not.toHaveBeenCalled();
    expect(analytics.getAlgorithms).not.toHaveBeenCalled();
    expect(analytics.getAnalytics).not.toHaveBeenCalled();
    expect(container.querySelector("[data-testid=board]")).toBeNull();
  });

  it("hands an Overwatch tournament's board its owner scope, game metadata and permissions, under one hero", async () => {
    await render("tournamentId=20&algorithm=2");

    expect(registry.loadAnalyticsUI).toHaveBeenCalledWith("overwatch");
    expect(container.querySelector("[data-testid=board]")?.textContent).toBe("board of 20");
    const props = seen.props as SlotProps["analytics"];
    expect(props).toMatchObject({ tournamentId: 20, workspaceId: OW_WORKSPACE, canReadV2: true, canUpdate: false });
    expect(props.metadata.discipline.code).toBe("overwatch");
    // The host's hero carries the board's controls and counts, and the tournament's own identity.
    expect(container.textContent).toContain("Overwatch Cup");
    expect(container.textContent).toContain("Linear");
    expect(container.querySelectorAll("h1")).toHaveLength(1);
    expect(container.textContent).not.toContain("not available");
  });
});
