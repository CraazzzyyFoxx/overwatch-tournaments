// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  LogHistoryResponse,
  LogProcessingRecord,
  LogProcessingStats
} from "@/types/admin.types";
import { TournamentLogsTab } from "./TournamentLogsTab";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getLogStats = vi.fn();
const getLogHistory = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getLogStats: (...args: unknown[]) => getLogStats(...args),
    getLogHistory: (...args: unknown[]) => getLogHistory(...args),
    retryLogRecord: vi.fn(),
    processAllTournamentLogs: vi.fn()
  }
}));
vi.mock("@/hooks/useRealtimeTopic", () => ({ useRealtimeTopic: () => {} }));
vi.mock("next-intl", () => ({
  useFormatter: () => ({ dateTime: (value: Date) => value.toISOString() })
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

/** The status chip lives in the URL now, so the console needs a router. */
const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});

let rerender: (() => void) | null = null;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/tournaments/78/matches/logs",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

const STATS: LogProcessingStats = {
  total: 128,
  pending: 4,
  processing: 1,
  done: 120,
  failed: 3,
  avg_duration_seconds: 4.25,
  last_created_at: "2026-07-30T17:04:00Z"
};

function record(id: number, overrides: Partial<LogProcessingRecord> = {}): LogProcessingRecord {
  return {
    id,
    tournament_id: 78,
    tournament_name: "OWT 78",
    attached_encounter_id: null,
    attached_encounter_name: null,
    filename: `logs/round_${id}.txt`,
    status: "done",
    source: "upload",
    uploader_name: "operator",
    error_message: null,
    attempts: 1,
    created_at: "2026-07-30T17:00:00Z",
    started_at: "2026-07-30T17:00:00Z",
    finished_at: "2026-07-30T17:00:04Z",
    ...overrides
  };
}

/** A full page (the console requests 25) so paging behaves as it does in production. */
const FIRST_PAGE: LogHistoryResponse = {
  items: [
    record(1, { status: "failed", error_message: "502: gateway timeout" }),
    record(99, { status: "pending", attempts: 3, started_at: null, finished_at: null }),
    ...Array.from({ length: 23 }, (_unused, index) => record(index + 2))
  ],
  total: 128
};

// Roots are tracked so afterEach can tear them down. Without it React 19 leaves a
// scheduler callback queued past the end of the file, and when vitest disposes the
// happy-dom environment that callback dereferences `window` — an unhandled
// `ReferenceError: window is not defined` that fails the whole run while every
// test still reports green. It only shows up under CI timing, which is why it
// surfaced the first time this suite ran there.
const mounted: { root: Root; container: HTMLElement }[] = [];

async function settle(turns = 5) {
  for (let turn = 0; turn < turns; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

/**
 * Renders through a factory: React bails out of re-rendering a child whose
 * element is referentially identical, so a URL-driven re-render would never
 * reach the console under test.
 */
function Harness({ render }: Readonly<{ render: () => ReactNode }>) {
  const [, force] = useState(0);
  // Published from an effect, not during render: writing a module-scope binding
  // while rendering is a side effect the react-compiler rules reject.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <>{render()}</>;
}

async function mount(tournamentId: number | null = 78) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <Harness
          render={() => (
            <TournamentLogsTab
              tournamentId={tournamentId}
              workspaceId={1}
              encounters={[]}
              canUploadLogs={false}
              enabled
            />
          )}
        />
      </QueryClientProvider>
    );
  });
  await settle();
  return container;
}

async function click(element: Element | null | undefined) {
  expect(element).toBeTruthy();
  await act(async () => {
    (element as HTMLElement).dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle(2);
}

function button(scope: ParentNode, text: string) {
  return Array.from(scope.querySelectorAll("button")).find(
    (element) => element.textContent?.trim() === text
  );
}

function commandItem(label: string) {
  return Array.from(document.querySelectorAll('[cmdk-item=""]')).find(
    (item) => item.textContent?.trim().startsWith(label)
  );
}

beforeEach(() => {
  getLogStats.mockReset().mockResolvedValue(STATS);
  getLogHistory.mockReset().mockResolvedValue(FIRST_PAGE);
  replace.mockClear();
  window.history.replaceState(null, "", "/admin/tournaments/78/matches/logs");
});

afterEach(async () => {
  await act(async () => {
    for (const { root, container } of mounted.splice(0)) {
      root.unmount();
      container.remove();
    }
  });
  document.body.innerHTML = "";
});

describe("TournamentLogsTab", () => {
  it("labels each status option with the scope-wide count, not the loaded rows", async () => {
    const scope = await mount();

    // Two interesting rows are loaded, yet every count describes all 128
    // records — the aggregate, not the page.
    await click(scope.querySelector('button[aria-label="Add filter"]'));
    await click(commandItem("Status"));

    const options = Array.from(document.querySelectorAll('[cmdk-item=""]'))
      .map((node) => node.textContent)
      .join("|");
    expect(options).toContain("Failed3");
    expect(options).toContain("Queued4");
    expect(scope.textContent).toContain("128 logs");
    expect(getLogStats).toHaveBeenCalledWith(78);
  });

  it("asks the server for the first page, filters included", async () => {
    await mount();

    expect(getLogHistory).toHaveBeenCalledWith(78, {
      limit: 25,
      offset: 0,
      status: undefined,
      search: ""
    });
  });

  it("puts the picked status in the URL and sends it to the server", async () => {
    // The old toggle group kept this in component state, so "show me the
    // failures" could not be linked to anyone.
    const scope = await mount();

    await click(button(scope, "Show failed"));

    expect(new URLSearchParams(window.location.search).get("status")).toBe("failed");
    await settle();
    expect(getLogHistory).toHaveBeenLastCalledWith(78, {
      limit: 25,
      offset: 0,
      status: "failed",
      search: ""
    });
  });

  it("restores the status from the URL on load", async () => {
    window.history.replaceState(null, "", "/admin/tournaments/78/matches/logs?status=failed");
    await mount();

    expect(getLogHistory).toHaveBeenCalledWith(78, {
      limit: 25,
      offset: 0,
      status: "failed",
      search: ""
    });
  });

  it("reads the workspace when no tournament scopes it", async () => {
    // The same console backs `/admin/matches?view=logs`, where there is no
    // tournament to scope by — both endpoints take the workspace instead.
    await mount(null);

    expect(getLogStats).toHaveBeenCalledWith(undefined, { workspaceId: 1 });
    expect(getLogHistory).toHaveBeenCalledWith(undefined, {
      limit: 25,
      offset: 0,
      status: undefined,
      search: "",
      workspaceId: 1
    });
  });

  it("reports loaded-vs-matched progress and offers the next page", async () => {
    const scope = await mount();

    const statuses = [...scope.querySelectorAll("output")].map((node) => node.textContent);
    expect(statuses).toContain("Showing 25 of 128 logs");
    expect(scope.textContent).toContain("Load more logs");
  });

  it("names the failure and scopes the bulk retry to what is loaded", async () => {
    const scope = await mount();

    expect(scope.textContent).toContain("gateway timeout");
    expect(scope.textContent).toContain("Retry 1 loaded");
  });

  it("offers a requeue for a queued row the worker dropped", async () => {
    const scope = await mount();

    // "Queued" rows used to have no control at all: only `failed` got a button,
    // so a log whose queue message expired was stuck with no way out.
    const labels = [...scope.querySelectorAll("button[aria-label]")].map((node) =>
      node.getAttribute("aria-label")
    );
    expect(labels).toContain("Requeue log round_99.txt");
    expect(labels).toContain("Retry log round_1.txt");
    // Attempt count surfaces the requeue loop on the row itself.
    expect(scope.textContent).toContain("×3");
  });

  it("points forward when the tournament has no logs at all", async () => {
    getLogHistory.mockResolvedValue({ items: [], total: 0 });
    getLogStats.mockResolvedValue({
      ...STATS,
      total: 0,
      pending: 0,
      processing: 0,
      done: 0,
      failed: 0
    });

    const scope = await mount();

    expect(scope.textContent).toContain("No logs for this tournament yet");
    expect(scope.textContent).not.toContain("Clear filters");
  });
});
