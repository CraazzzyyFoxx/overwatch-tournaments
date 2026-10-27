// @vitest-environment happy-dom
import { existsSync } from "node:fs";
import { join } from "node:path";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { DraftBoard, type DraftOwner } from "@/components/draft/DraftBoard";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Module mocks are process-wide in bun: every mock of next-intl in the draft
// suite exposes the same hooks, or whichever file loads first breaks the rest.
vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => `draftRedesign.${key}`
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: () => "", number: (value: number) => String(value), relativeTime: () => "" })
}));

// The room around the board: only what it reads before it has a board to show.
const getSessionBoard = vi.fn();
vi.mock("@/services/draft.service", () => ({ default: { getSessionBoard: () => getSessionBoard() } }));
vi.mock("@/services/realtime.service", () => ({ realtimeClient: { subscribe: () => () => {}, resubscribe: () => {} } }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/draft/5",
  useRouter: () => ({ replace: () => {} }),
  useSearchParams: () => new URLSearchParams()
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) =>
    React.createElement("a", { href }, children)
}));
vi.mock("@/hooks/useAuthProfile", () => ({ useAuthProfile: () => ({ user: null }) }));
vi.mock("@/hooks/useDisciplineMetadata", () => ({ useDisciplineMetadata: () => ({ data: null }) }));
vi.mock("@/hooks/useCurrentWorkspace", () => ({ useDivisionGrid: () => ({ tiers: [] }) }));
vi.mock("@/components/chat/RoomChat", () => ({ RoomChat: () => null }));

const componentDir = import.meta.dirname;
const skeletonPath = join(componentDir, "DraftRoomSkeleton.tsx");
const loadingStatePath = join(componentDir, "draft-loading-state.ts");
const skeletonModule = existsSync(skeletonPath) ? await import("@/components/draft/DraftRoomSkeleton") : null;
const loadingStateModule = existsSync(loadingStatePath)
  ? await import("@/components/draft/draft-loading-state")
  : null;

const OWNER: DraftOwner = {
  workspaceId: 2,
  discipline: "overwatch",
  name: "Cup #41",
  href: "/tournaments/5",
  divisionGrid: null,
  isOrganizer: false
};

/** The real room for session 1, as it first mounts. */
async function renderBoard(): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    createRoot(container).render(
      React.createElement(
        QueryClientProvider,
        { client },
        React.createElement(DraftBoard, { sessionId: 1, owner: OWNER })
      )
    );
  });
  return container;
}

describe("standalone Draft loading skeleton", () => {
  it("shows the initial skeleton only for an active first fetch without data", () => {
    expect(loadingStateModule).not.toBeNull();
    if (!loadingStateModule) return;

    const shouldShow = loadingStateModule.shouldShowInitialDraftSkeleton;

    expect(shouldShow({ data: undefined, isPending: true, isFetching: true })).toBe(true);
    expect(shouldShow({ data: undefined, isPending: true, isFetching: false })).toBe(false);
    expect(shouldShow({ data: undefined, isPending: false, isFetching: false })).toBe(false);
    expect(shouldShow({ data: { id: 72 }, isPending: false, isFetching: true })).toBe(false);
    expect(shouldShow({ data: { id: 72 }, isPending: false, isFetching: false })).toBe(false);
  });

  it("renders one localized busy region around non-interactive Draft geometry", () => {
    expect(skeletonModule).not.toBeNull();
    if (!skeletonModule) return;

    const html = renderToStaticMarkup(React.createElement(skeletonModule.DraftRoomSkeleton));

    expect(html.match(/role="status"/g)).toHaveLength(1);
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain("draftRedesign.loadingTitle");
    expect(html).toContain('aria-hidden="true"');
    expect(html).not.toMatch(/<(?:a|button|h[1-6])\b/);
    expect(html).not.toMatch(/Loader2|animate-spin|spinner/i);
  });

  it("matches the loaded room: header, clock strip, pool and teams panels", () => {
    expect(skeletonModule).not.toBeNull();
    if (!skeletonModule) return;

    for (const Skeleton of [skeletonModule.DraftRoomSkeleton, skeletonModule.DraftBoardSkeleton]) {
      const html = renderToStaticMarkup(React.createElement(Skeleton));

      for (const region of [
        "header",
        "back-action",
        "status-pill",
        "clock-strip",
        "timer",
        "tick-track",
        "pool",
        "teams"
      ]) {
        expect(html).toContain(`data-draft-skeleton="${region}"`);
      }

      expect(html.match(/data-draft-skeleton="pool-row"/g)?.length).toBeGreaterThanOrEqual(6);
      expect(html.match(/data-draft-skeleton="team-row"/g)?.length).toBeGreaterThanOrEqual(4);
    }
  });

  it("shows the board's skeleton while the session's first board read runs", async () => {
    getSessionBoard.mockReturnValue(Promise.withResolvers().promise);
    const container = await renderBoard();

    expect(container.querySelector('[aria-busy="true"] [data-draft-skeleton="pool"]')).not.toBeNull();
    expect(container.querySelector(".animate-spin")).toBeNull();
    expect(container.textContent).not.toContain("draftRedesign.loadErrorTitle");
  });

  it("offers a retry and the way back when the session's board cannot be read", async () => {
    getSessionBoard.mockRejectedValue(new Error("board read failed"));
    const container = await renderBoard();

    await vi.waitFor(() => expect(container.querySelector("h1")?.textContent).toBe("draftRedesign.loadErrorTitle"));
    expect(container.querySelector('[aria-busy="true"]')).toBeNull();
    expect([...container.querySelectorAll("button")].map((button) => button.textContent)).toContain("draftRedesign.retry");
    expect(container.querySelector('a[href="/tournaments/5"]')).not.toBeNull();
  });

  it("disables shimmer for reduced motion", () => {
    // The blocks are `ui/skeleton`, which stops its pulse under reduced motion.
    expect(skeletonModule).not.toBeNull();
    if (!skeletonModule) return;
    const html = renderToStaticMarkup(React.createElement(skeletonModule.DraftRoomSkeleton));
    const blocks = html.match(/class="[^"]*animate-pulse[^"]*"/g) ?? [];
    expect(blocks.length).toBeGreaterThan(0);
    for (const block of blocks) expect(block).toContain("motion-reduce:animate-none");
  });
});
