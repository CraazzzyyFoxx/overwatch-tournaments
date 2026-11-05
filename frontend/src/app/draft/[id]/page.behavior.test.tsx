// @vitest-environment happy-dom
//
// The public draft room of a tournament. What is pinned here:
//  1. the room is the session the tournament's current-draft lookup names;
//  2. once that session ends or is erased, the lookup runs again, so the
//     organizer's next draft is the one the page follows;
//  3. the room's own skeleton holds the page while the tournament loads.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import type { DraftBoard, DraftStatus } from "@/types/draft.types";

import PublicDraftRoomPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TOURNAMENT = {
  id: 5,
  slug: "cup-41",
  name: "Cup #41",
  workspace_id: 2,
  discipline: "overwatch",
  team_formation: "draft",
  division_grid_version: null,
  flow_nodes: [{ id: 9, kind: "formation", name: "Teams", status: "forming", config: { mode: "draft" }, schedule: [], stage_id: null }]
};

const mocks = vi.hoisted(() => ({
  getTournamentBoard: vi.fn(),
  getSessionBoard: vi.fn(),
  tournamentQuery: {} as Record<string, unknown>
}));

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "5" }), useSearchParams: () => new URLSearchParams(), redirect: vi.fn() }));
vi.mock("next-intl", () => ({ useLocale: () => "en", useTranslations: () => (key: string) => key }));
vi.mock("@/hooks/useTournamentClientData", () => ({ useTournamentQuery: () => mocks.tournamentQuery }));
vi.mock("@/hooks/useEntityWorkspace", () => ({ useEntityWorkspace: () => {} }));
vi.mock("@/hooks/usePermissions", () => ({ usePermissions: () => ({ canAccessPermission: () => false }) }));
vi.mock("@/services/draft.service", () => ({
  default: { getTournamentBoard: mocks.getTournamentBoard, getSessionBoard: mocks.getSessionBoard }
}));
// The room itself has its own tests; here it only shows which session it was handed.
vi.mock("@/components/draft/DraftBoard", () => ({
  DraftBoard: ({ sessionId }: { sessionId: number }) => <div data-session={sessionId} />,
  DraftStateFrame: ({ title }: { title: string }) => <p>{title}</p>
}));

function boardOf(sessionId: number, status: DraftStatus): DraftBoard {
  return { session: { id: sessionId, tournament_id: 5, status } } as unknown as DraftBoard;
}

let container: HTMLElement;
let root: Root;
let client: QueryClient;

async function settle() {
  for (let turn = 0; turn < 4; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function render() {
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <PublicDraftRoomPage />
      </QueryClientProvider>
    );
  });
  await settle();
}

const followed = () => container.querySelector("[data-session]")?.getAttribute("data-session") ?? null;

beforeEach(() => {
  mocks.tournamentQuery = { data: TOURNAMENT, isPending: false, isFetching: false, isError: false };
  mocks.getTournamentBoard.mockReset().mockResolvedValue(boardOf(1, "live"));
  mocks.getSessionBoard.mockReset().mockImplementation(async (sessionId: number) => boardOf(sessionId, "live"));
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  client.clear();
});

describe("the public draft room", () => {
  it("follows the tournament's next draft once the one it shows has finished", async () => {
    await render();
    expect(followed()).toBe("1");

    mocks.getTournamentBoard.mockResolvedValue(boardOf(2, "ready"));
    // What the room's realtime patch does to its board when the last pick lands.
    await act(async () => {
      client.setQueryData(tournamentQueryKeys.draftSessionBoard(1), boardOf(1, "completed"));
    });
    await settle();

    expect(followed()).toBe("2");
  });

  it("follows the tournament's next draft once the one it shows is erased", async () => {
    await render();
    expect(followed()).toBe("1");

    mocks.getTournamentBoard.mockResolvedValue(boardOf(2, "ready"));
    mocks.getSessionBoard.mockImplementation(async (sessionId: number) => {
      if (sessionId === 1) throw new Error("Draft session not found");
      return boardOf(sessionId, "ready");
    });
    // The deletion's `session_updated` re-reads the board, which is gone.
    await act(async () => {
      await client.invalidateQueries({ queryKey: tournamentQueryKeys.draftSessionBoard(1) });
    });
    await settle();

    expect(followed()).toBe("2");
  });

  it("says there is no draft yet when the tournament has none", async () => {
    mocks.getTournamentBoard.mockResolvedValue(null);
    await render();

    expect(followed()).toBeNull();
    expect(container.textContent).toContain("emptyTitle");
  });

  it("holds the page on the room's skeleton while the tournament loads", async () => {
    mocks.tournamentQuery = { data: undefined, isPending: true, isFetching: true, isError: false };
    await render();

    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(mocks.getTournamentBoard).not.toHaveBeenCalled();
  });
});
