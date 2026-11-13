// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactElement, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  LogHistoryResponse,
  LogProcessingRecord,
  LogProcessingStats
} from "@/types/admin.types";
import type { Encounter } from "@/types/encounter.types";
import { notify } from "@/lib/notify";
import { TournamentLogsTab } from "./TournamentLogsTab";
import { ApiError } from "@/lib/api/error";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getLogStats = vi.fn();
const getLogHistory = vi.fn();
const retryLogRecord = vi.fn();
const getEncounter = vi.fn();
const bindLogRecord = vi.fn();
const getGameObservation = vi.fn();
const getTournaments = vi.fn();
const getEncounters = vi.fn();

vi.mock("@/services/encounter.service", () => ({
  default: {
    getEncounter: (...args: unknown[]) => getEncounter(...args),
    getAll: (...args: unknown[]) => getEncounters(...args)
  }
}));
vi.mock("@/services/tournament.service", () => ({
  default: { getAll: (...args: unknown[]) => getTournaments(...args) }
}));

vi.mock("@/services/admin.service", () => ({
  default: {
    getLogStats: (...args: unknown[]) => getLogStats(...args),
    getLogHistory: (...args: unknown[]) => getLogHistory(...args),
    retryLogRecord: (...args: unknown[]) => retryLogRecord(...args),
    bindLogRecord: (...args: unknown[]) => bindLogRecord(...args),
    getGameObservation: (...args: unknown[]) => getGameObservation(...args),
    processAllTournamentLogs: vi.fn()
  }
}));
vi.mock("@/hooks/useRealtimeTopic", () => ({ useRealtimeTopic: () => {} }));
vi.mock("@/lib/datetime/client", () => ({
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
  awaiting_link: 0,
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
    custom_game_id: null,
    custom_game_name: null,
    attached_encounter_game_id: null,
    filename: `logs/round_${id}.txt`,
    status: "done",
    source: "upload",
    raw_status: "available",
    raw_available: true,
    uploader_name: "operator",
    error_message: null,
    error: null,
    attempts: 1,
    created_at: "2026-07-30T17:00:00Z",
    started_at: "2026-07-30T17:00:00Z",
    finished_at: "2026-07-30T17:00:04Z",
    observation_revision: null,
    is_current_provenance: false,
    teams: [],
    ...overrides
  };
}

const PLAYOFF = {
  id: 6662,
  name: "Home vs Away",
  tournament_id: 78,
  round: -3,
  stage: { name: "Playoffs" },
  stage_item: null
} as Encounter;

function game(id: number, position: number, state: Encounter["games"][number]["state"] = "planned"): Encounter["games"][number] {
  return {
    id,
    position,
    map_id: 21,
    map: { id: 21, name: "Ilios" } as Encounter["games"][number]["map"],
    state,
    result_source: null,
    result_version: 0,
    confirmed_at: null,
    teams: []
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
      if (vi.isFakeTimers()) {
        await vi.advanceTimersByTimeAsync(0);
      } else {
        const { promise, resolve } = Promise.withResolvers<void>();
        setTimeout(resolve, 0);
        await promise;
      }
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

async function mount(tournamentId: number | null = 78, encounters: Encounter[] = []) {
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
              encounters={encounters}
              canUploadLogs={false}
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

function menuItem(label: string) {
  return Array.from(document.querySelectorAll("[role='menuitem']")).find(
    (item) => item.textContent?.trim() === label
  );
}

beforeEach(() => {
  getLogStats.mockReset().mockResolvedValue(STATS);
  getLogHistory.mockReset().mockResolvedValue(FIRST_PAGE);
  replace.mockClear();
  retryLogRecord.mockReset().mockResolvedValue(record(1, { status: "pending" }));
  getTournaments.mockReset();
  getEncounters.mockReset();
  getEncounter.mockReset().mockResolvedValue({
    ...PLAYOFF,
    games: [game(801, 1), game(907, 2), game(999, 3, "cancelled")]
  });
  vi.mocked(notify.success).mockClear();
  vi.mocked(notify.apiError).mockClear();
  vi.mocked(notify.error).mockClear();
  bindLogRecord.mockReset();
  getGameObservation.mockReset().mockResolvedValue({
    encounter_game_id: 801,
    match_id: null,
    revision: 0,
    ingest_job_id: null,
    is_historical: false
  });
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
  vi.useRealTimers();
});

const SEATED = {
  ...PLAYOFF,
  teams: [{ id: 11, name: "Home" }, { id: 22, name: "Away" }],
  games: [{ ...game(801, 1), teams: [{ encounter_team_id: 11 }, { encounter_team_id: 22 }] }]
};

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

    await click(scope.querySelector('button[aria-label="Add filter"]'));
    await click(commandItem("Status"));
    await click(commandItem("Failed"));

    expect(new URLSearchParams(window.location.search).get("status")).toBe("failed");
    await settle();
    // Not "last": the table prefetches the next page after this one.
    expect(getLogHistory).toHaveBeenCalledWith(78, {
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

  it("pages through the server by offset", async () => {
    const scope = await mount();

    expect(scope.textContent).toContain("1–25 of 128");
    await click(scope.querySelector('button[aria-label="Next page"]'));
    await settle();

    // The table prefetches the next page, so page 2's request is not proof by itself.
    expect(scope.textContent).toContain("26–50 of 128");
    expect(new URLSearchParams(window.location.search).get("page")).toBe("2");
    expect(getLogHistory).toHaveBeenCalledWith(78, {
      limit: 25,
      offset: 25,
      status: undefined,
      search: ""
    });
  });

  it("names the failure and bulk-retries only rows that are not done", async () => {
    const scope = await mount();

    expect(scope.textContent).toContain("gateway timeout");
    // A processed log has nothing to retry, so it cannot join the selection.
    expect(scope.querySelector('button[aria-label="Select row 2"]')).toBeNull();

    await click(scope.querySelector('button[aria-label="Select row 1"]'));
    await click(scope.querySelector('button[aria-label="Select row 99"]'));
    expect(button(scope, "Retry 2")).toBeTruthy();
  });

  it("offers a requeue for a queued row the worker dropped", async () => {
    const scope = await mount();

    // "Queued" rows used to have no control at all: only `failed` got a button,
    // so a log whose queue message expired was stuck with no way out.
    const labels = [...scope.querySelectorAll("button[aria-label]")].map((node) =>
      node.getAttribute("aria-label")
    );
    expect(labels).toContain("Actions for round_99.txt");
    expect(labels).toContain("Actions for round_1.txt");
    expect(labels).not.toContain("Actions for round_2.txt");
    // Attempt count surfaces the requeue loop on the row itself.
    expect(scope.textContent).toContain("×3");
  });

  it("does not offer retry or attachment while the job is processing", async () => {
    getLogHistory.mockResolvedValue({ items: [record(17, { status: "processing" })], total: 1 });
    const scope = await mount(78, [PLAYOFF]);
    expect(scope.textContent).toContain("Processing");
    expect(scope.querySelector('button[aria-label="Select row 17"]')).toBeNull();
    expect(scope.querySelector('button[aria-label="Actions for round_17.txt"]')).toBeNull();
  });

  it.each([
    ["missing", "Raw log file is missing"],
    ["conflict", "recorded hash"],
    ["unverified", "not been verified"]
  ] as const)("keeps %s raw history visible but offers no retry or attachment", async (raw_status, explanation) => {
    getLogHistory.mockResolvedValue({
      items: [record(17, { status: "failed", raw_status, raw_available: false })],
      total: 1
    });
    const scope = await mount(78, [PLAYOFF]);
    expect(scope.textContent).toContain("round_17.txt");
    expect(scope.textContent).toContain(explanation);
    // Absent, not disabled: the row says why, and nothing invites a guess.
    expect(button(scope, "Retry")).toBeUndefined();
    expect(scope.querySelector('button[aria-label="Select row 17"]')).toBeNull();
    expect(scope.querySelector('button[aria-label="Actions for round_17.txt"]')).toBeNull();
    expect(retryLogRecord).not.toHaveBeenCalled();
  });

  it("does not present historical references or unbound parsed observations as safe to reprocess", async () => {
    getLogHistory.mockResolvedValue({
      items: [
        record(17, { status: "failed", source: "historical_reference" }),
        record(18, { status: "failed", attached_encounter_id: 6662, attached_encounter_game_id: null })
      ],
      total: 2
    });
    const scope = await mount(78, [PLAYOFF]);
    expect(scope.textContent).toContain("Historical source reference");
    expect(scope.textContent).toContain("Game binding is unconfirmed");
    expect(scope.querySelector('button[aria-label="Select row 17"]')).toBeNull();
    expect(scope.querySelector('button[aria-label="Select row 18"]')).toBeNull();
    expect(scope.querySelector('button[aria-label="Actions for round_17.txt"]')).toBeNull();
    expect(scope.querySelector('button[aria-label="Actions for round_18.txt"]')).toBeNull();
    expect(retryLogRecord).not.toHaveBeenCalled();
  });

  it("requires an actual noncancelled game when resolving two live games on the same map", async () => {
    getLogHistory.mockResolvedValue({
      items: [record(17, { status: "awaiting_link", tournament_id: null, tournament_name: null })],
      total: 1
    });
    const scope = await mount(78, [PLAYOFF]);

    await click(scope.querySelector('button[aria-label="Actions for round_17.txt"]'));
    await click(menuItem("Attach to game…"));
    await click(document.querySelector('button[aria-label="Pick an encounter"]'));
    await click(commandItem("Home vs Away · Playoffs · LB Round 3"));
    expect(button(document, "Attach and reprocess")?.disabled).toBe(true);
    await click(document.querySelector('button[aria-label="Pick a game"]'));
    expect(commandItem("Game 3")).toBeUndefined();
    await click(commandItem("Game 2 · Ilios · #907"));
    await click(button(document, "Attach and reprocess"));

    expect(retryLogRecord).toHaveBeenCalledWith(17, {
      encounter_id: 6662,
      encounter_game_id: 907
    });
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(notify.success).toHaveBeenCalledWith("Log attached and queued");
  });

  it("renders and filters awaiting-link jobs with null tournament hints and native source kinds", async () => {
    getLogStats.mockResolvedValue({ ...STATS, awaiting_link: 9 });
    getLogHistory.mockResolvedValue({
      items: [record(17, {
        status: "awaiting_link",
        tournament_id: null,
        tournament_name: null,
        source: "desktop_agent"
      })],
      total: 1
    });
    const scope = await mount(null);
    expect(scope.textContent).toContain("Awaiting link");
    expect(scope.querySelector('[title*="desktop_agent"]')).not.toBeNull();
    await click(scope.querySelector('button[aria-label="Add filter"]'));
    await click(commandItem("Status"));
    expect(commandItem("Awaiting link")?.textContent).toContain("9");
    await click(commandItem("Awaiting link"));
    expect(new URLSearchParams(window.location.search).get("status")).toBe("awaiting_link");
    expect(getLogHistory).toHaveBeenLastCalledWith(undefined, expect.objectContaining({
      status: "awaiting_link", workspaceId: 1
    }));
  });

  it("does not poll an awaiting-only queue or present it as failed or processed", async () => {
    vi.useFakeTimers();
    getLogStats.mockResolvedValue({
      ...STATS, total: 1, pending: 0, processing: 0, failed: 0, done: 0, awaiting_link: 1
    });
    getLogHistory.mockResolvedValue({ items: [record(17, { status: "awaiting_link" })], total: 1 });
    const scope = await mount();
    const reads = getLogHistory.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(getLogHistory).toHaveBeenCalledTimes(reads);
    expect(scope.textContent).toContain("Awaiting link");
    expect(scope.textContent).not.toContain("Processed");
    expect(scope.textContent).not.toContain("failed to process");
  });

  it("clears the selected game when the encounter changes", async () => {
    const scope = await mount(78, [PLAYOFF, { ...PLAYOFF, id: 6663, name: "Other teams" }]);
    await click(scope.querySelector('button[aria-label="Actions for round_1.txt"]'));
    await click(menuItem("Attach to game…"));
    await click(document.querySelector('button[aria-label="Pick an encounter"]'));
    await click(commandItem("Home vs Away"));
    await click(document.querySelector('button[aria-label="Pick a game"]'));
    await click(commandItem("Game 2 · Ilios · #907"));
    expect(button(document, "Attach and reprocess")?.disabled).toBe(false);
    getEncounter.mockResolvedValue({ ...PLAYOFF, id: 6663, games: [game(1201, 1)] });
    await click(document.querySelector('button[aria-label="Pick an encounter"]'));
    await click(commandItem("Other teams"));
    expect(button(document, "Attach and reprocess")?.disabled).toBe(true);
    expect(retryLogRecord).not.toHaveBeenCalled();
  });

  it("keeps attachment pending and preserves the dialog and selection when the server rejects it", async () => {
    const retry = Promise.withResolvers<LogProcessingRecord>();
    retryLogRecord.mockReturnValue(retry.promise);
    const scope = await mount(78, [PLAYOFF]);
    await click(scope.querySelector('button[aria-label="Actions for round_1.txt"]'));
    await click(menuItem("Attach to game…"));
    await click(document.querySelector('button[aria-label="Pick an encounter"]'));
    await click(commandItem("Home vs Away"));
    await click(document.querySelector('button[aria-label="Pick a game"]'));
    await click(commandItem("Game 2 · Ilios · #907"));
    await click(button(document, "Attach and reprocess"));
    expect(button(document, "Attach and reprocess")?.disabled).toBe(true);
    expect(notify.success).not.toHaveBeenCalled();
    const error = new Error("This game cannot be rebound");
    await act(async () => { retry.reject(error); });
    await settle();
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    expect(document.body.textContent).toContain("Game 2 · Ilios · #907");
    expect(button(document, "Attach and reprocess")?.disabled).toBe(false);
    expect(notify.apiError).toHaveBeenCalledWith(error);
    expect(notify.success).not.toHaveBeenCalled();
  });

  it("blocks attachment when games cannot be loaded or only cancelled games remain", async () => {
    getEncounter.mockRejectedValue(new Error("Forbidden"));
    const scope = await mount(78, [PLAYOFF]);
    await click(scope.querySelector('button[aria-label="Actions for round_1.txt"]'));
    await click(menuItem("Attach to game…"));
    await click(document.querySelector('button[aria-label="Pick an encounter"]'));
    await click(commandItem("Home vs Away"));
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("Could not load games");
    expect(button(document, "Attach and reprocess")?.disabled).toBe(true);
    getEncounter.mockResolvedValue({ ...PLAYOFF, games: [game(999, 1, "cancelled")] });
    await click(button(document, "Reload games"));
    expect(document.body.textContent).toContain("No noncancelled games");
    expect(button(document, "Attach and reprocess")?.disabled).toBe(true);
    expect(retryLogRecord).not.toHaveBeenCalled();
  });

  it("says so plainly when the tournament has no logs at all", async () => {
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

    expect(scope.textContent).toContain("No logs yet.");
    expect(scope.textContent).not.toContain("Clear filters");
  });

  it("reparses a processed log with the revision its row showed", async () => {
    getLogHistory.mockResolvedValue({
      items: [record(30, { is_current_provenance: true, observation_revision: 3, attached_encounter_game_id: 801 })],
      total: 1
    });
    const scope = await mount();
    await click(scope.querySelector('button[aria-label="Actions for round_30.txt"]'));
    await click(menuItem("Reparse log"));
    expect(retryLogRecord).toHaveBeenCalledWith(30, { reparse: true, expected_revision: 3 });
    expect(notify.success).toHaveBeenCalledWith("1 log queued or reparsed");
  });

  it("bulk-reparses with each row's captured revision and names the rows that went stale or busy", async () => {
    getLogHistory.mockResolvedValue({
      items: [
        record(30, { is_current_provenance: true, observation_revision: 2 }),
        record(31, { is_current_provenance: true, observation_revision: 5 }),
        record(32, { is_current_provenance: true, observation_revision: 1 }),
        record(33, { status: "failed" }),
        // Superseded: no longer any game's current evidence, so it cannot be reparsed or selected.
        record(34, { is_current_provenance: false, observation_revision: null })
      ],
      total: 5
    });
    retryLogRecord.mockImplementation(async (id: number) => {
      if (id === 31) throw new ApiError(409, [{ msg: "changed", code: "stale_revision" }]);
      if (id === 32) throw new ApiError(409, [{ msg: "busy", code: "ingest_busy" }]);
      return record(id);
    });
    const scope = await mount();
    expect(scope.querySelector('button[aria-label="Select row 34"]')).toBeNull();
    for (const id of [30, 31, 32, 33]) await click(scope.querySelector(`button[aria-label="Select row ${id}"]`));
    await click(button(scope, "Retry 4"));

    expect(retryLogRecord).toHaveBeenCalledWith(30, { reparse: true, expected_revision: 2 });
    expect(retryLogRecord).toHaveBeenCalledWith(31, { reparse: true, expected_revision: 5 });
    expect(retryLogRecord).toHaveBeenCalledWith(32, { reparse: true, expected_revision: 1 });
    expect(retryLogRecord).toHaveBeenCalledWith(33, undefined);
    const [title, options] = vi.mocked(notify.error).mock.calls[0]!;
    expect(title).toBe("Processed 2 of 4 logs");
    const description = renderToStaticMarkup(options?.description as ReactElement);
    expect(description).toContain("round_31.txt: The game’s statistics changed");
    expect(description).toContain("round_32.txt: This log is being processed right now");
    expect(description).not.toContain("round_30.txt");
  });

  it("shows the structured error message and its issue paths, and keeps awaiting jobs awaiting", async () => {
    getLogHistory.mockResolvedValue({
      items: [
        record(40, {
          status: "failed",
          error_message: "The document is invalid",
          error: {
            code: "invalid_document",
            message: "The document is invalid",
            issues: [{ path: ["teams", 0, "players"], code: "unknown_hero", message: "Unknown hero Ana2" }]
          }
        }),
        record(41, { status: "awaiting_link" })
      ],
      total: 2
    });
    const scope = await mount();
    expect(scope.textContent).toContain("The document is invalid");
    expect(scope.querySelector("pre")?.textContent).toBe(
      "The document is invalid\nteams.0.players: Unknown hero Ana2"
    );
    expect(scope.textContent).toContain("Waiting for a game");
    expect(scope.textContent).not.toContain("Processed");
  });

  it("explains a historical observation as non-replaceable and offers no bind", async () => {
    getEncounter.mockResolvedValue(SEATED);
    getGameObservation.mockResolvedValue({
      encounter_game_id: 801,
      match_id: 9,
      revision: 2,
      ingest_job_id: null,
      is_historical: true
    });
    getLogHistory.mockResolvedValue({
      items: [
        record(17, {
          status: "awaiting_link",
          teams: [
            { key: "alpha", source_position: 1, participants: [] },
            { key: "beta", source_position: 2, participants: [] }
          ]
        })
      ],
      total: 1
    });
    const scope = await mount(78, [PLAYOFF]);
    await click(scope.querySelector('button[aria-label="Actions for round_17.txt"]'));
    await click(menuItem("Attach to game…"));
    await click(document.querySelector('button[aria-label="Pick an encounter"]'));
    await click(commandItem("Home vs Away"));
    await click(document.querySelector('button[aria-label="Pick a game"]'));
    await click(commandItem("Game 1 · Ilios · #801"));
    await click(document.querySelector('button[aria-label="Game team for log team alpha"]'));
    await click(commandItem("Home"));
    await click(document.querySelector('button[aria-label="Game team for log team beta"]'));
    await click(commandItem("Away"));
    expect(document.body.textContent).toContain("cannot be replaced by a log");
    expect(button(document, "Bind and publish")?.disabled).toBe(true);
    expect(bindLogRecord).not.toHaveBeenCalled();
  });

  it("binds a failed job that kept its document teams through the team-map flow", async () => {
    getEncounter.mockResolvedValue(SEATED);
    getLogHistory.mockResolvedValue({
      items: [
        record(18, {
          status: "failed",
          // A hint (encounter set, no game) is not an observation: it must not block an explicit bind.
          attached_encounter_id: 6662,
          attached_encounter_game_id: null,
          error: { code: "binding_mismatch", message: "mismatch", issues: [] },
          error_message: "mismatch",
          teams: [
            { key: "alpha", source_position: 1, participants: [] },
            { key: "beta", source_position: 2, participants: [] }
          ]
        })
      ],
      total: 1
    });
    bindLogRecord.mockResolvedValue({ id: 18, status: "done", error: null, binding: null });
    const scope = await mount(78, [PLAYOFF]);
    await click(scope.querySelector('button[aria-label="Actions for round_18.txt"]'));
    await click(menuItem("Attach to game…"));
    // The ordinary retry stays refused for a hint-only binding; the explicit bind is not.
    expect(scope.textContent).toContain("Game binding is unconfirmed");
    // The hinted encounter is preselected, so only the game is picked.
    await click(document.querySelector('button[aria-label="Pick a game"]'));
    await click(commandItem("Game 1 · Ilios · #801"));
    await click(document.querySelector('button[aria-label="Game team for log team alpha"]'));
    await click(commandItem("Home"));
    await click(document.querySelector('button[aria-label="Game team for log team beta"]'));
    await click(commandItem("Away"));
    await click(button(document, "Bind and publish"));
    expect(bindLogRecord).toHaveBeenCalledWith(18, {
      encounter_game_id: 801,
      teams: { alpha: 11, beta: 22 },
      expected_revision: 0
    });
    expect(retryLogRecord).not.toHaveBeenCalled();
  });

  it("binds an awaiting job to a cancelled position of a series entered whole", async () => {
    // A whole-series report cancels every unplayed position: the bind's only targets, often without a map.
    getEncounter.mockResolvedValue({
      ...SEATED,
      games: [
        {
          ...game(805, 1, "cancelled"),
          map_id: null,
          map: null,
          teams: [{ encounter_team_id: 11 }, { encounter_team_id: 22 }]
        }
      ]
    });
    getGameObservation.mockResolvedValue({
      encounter_game_id: 805,
      match_id: null,
      revision: 0,
      ingest_job_id: null,
      is_historical: false
    });
    getLogHistory.mockResolvedValue({
      items: [
        record(20, {
          status: "awaiting_link",
          attached_encounter_id: 6662,
          teams: [
            { key: "alpha", source_position: 1, participants: [] },
            { key: "beta", source_position: 2, participants: [] }
          ]
        })
      ],
      total: 1
    });
    bindLogRecord.mockResolvedValue({ id: 20, status: "done", error: null, binding: null });
    const scope = await mount(78, [PLAYOFF]);
    await click(scope.querySelector('button[aria-label="Actions for round_20.txt"]'));
    await click(menuItem("Attach to game…"));
    expect(getEncounter).toHaveBeenCalledWith(6662, { withCancelledGames: true });
    await click(document.querySelector('button[aria-label="Pick a game"]'));
    await click(commandItem("Game 1 · Unknown map · #805 · cancelled"));
    await click(document.querySelector('button[aria-label="Game team for log team alpha"]'));
    await click(commandItem("Home"));
    await click(document.querySelector('button[aria-label="Game team for log team beta"]'));
    await click(commandItem("Away"));
    await click(button(document, "Bind and publish"));
    expect(bindLogRecord).toHaveBeenCalledWith(20, {
      encounter_game_id: 805,
      teams: { alpha: 11, beta: 22 },
      expected_revision: 0
    });
  });

  it.each([
    ["a historical reference", { source: "historical_reference" }],
    ["an unavailable raw source", { raw_status: "missing", raw_available: false }]
  ] as const)("offers no explicit bind for a failed job with %s even when it has document teams", async (_name, overrides) => {
    getLogHistory.mockResolvedValue({
      items: [
        record(19, {
          status: "failed",
          teams: [{ key: "alpha", source_position: 1, participants: [] }],
          ...overrides
        })
      ],
      total: 1
    });
    const scope = await mount(78, [PLAYOFF]);
    expect(scope.querySelector('button[aria-label="Actions for round_19.txt"]')).toBeNull();
    expect(bindLogRecord).not.toHaveBeenCalled();
  });

  it.each([
    [4, "This game already has statistics (revision 4)"],
    [0, null]
  ] as const)("binds an awaiting job with the complete team map and expected_revision %i", async (revision, notice) => {
    getEncounter.mockResolvedValue({
      ...PLAYOFF,
      teams: [{ id: 11, name: "Home" }, { id: 22, name: "Away" }],
      games: [{ ...game(801, 1), teams: [{ encounter_team_id: 11 }, { encounter_team_id: 22 }] }]
    });
    // The occupant is deliberately absent from the history page: the revision comes from the game read.
    getGameObservation.mockResolvedValue({
      encounter_game_id: 801,
      match_id: revision > 0 ? 5 : null,
      revision,
      ingest_job_id: revision > 0 ? 30 : null,
      is_historical: false
    });
    getLogHistory.mockResolvedValue({
      items: [
        record(17, {
          status: "awaiting_link",
          teams: [
            { key: "alpha", source_position: 1, participants: ["Ana#1"] },
            { key: "beta", source_position: 2, participants: ["Bea#2"] }
          ]
        })
      ],
      total: 1
    });
    bindLogRecord.mockResolvedValue({ id: 17, status: "done", error: null, binding: null });
    const scope = await mount(78, [PLAYOFF]);

    await click(scope.querySelector('button[aria-label="Actions for round_17.txt"]'));
    await click(menuItem("Attach to game…"));
    await click(document.querySelector('button[aria-label="Pick an encounter"]'));
    await click(commandItem("Home vs Away"));
    await click(document.querySelector('button[aria-label="Pick a game"]'));
    await click(commandItem("Game 1 · Ilios · #801"));
    // The map is the operator's: nothing is preselected and nothing binds until every log team is seated.
    expect(button(document, "Bind and publish")?.disabled).toBe(true);
    expect(document.body.textContent).toContain("Ana#1");
    await click(document.querySelector('button[aria-label="Game team for log team alpha"]'));
    await click(commandItem("Away"));
    expect(button(document, "Bind and publish")?.disabled).toBe(true);
    await click(document.querySelector('button[aria-label="Game team for log team beta"]'));
    // A seat already given to another log team is not offered twice.
    expect(commandItem("Away")).toBeUndefined();
    await click(commandItem("Home"));
    if (notice) expect(document.body.textContent).toContain(notice);
    await click(button(document, "Bind and publish"));

    expect(bindLogRecord).toHaveBeenCalledWith(17, {
      encounter_game_id: 801,
      teams: { alpha: 22, beta: 11 },
      expected_revision: revision
    });
    expect(notify.success).toHaveBeenCalledWith("Log bound and published");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("keeps the bind dialog open and re-reads the game when the operator's revision is stale", async () => {
    getEncounter.mockResolvedValue({
      ...PLAYOFF,
      teams: [{ id: 11, name: "Home" }, { id: 22, name: "Away" }],
      games: [{ ...game(801, 1), teams: [{ encounter_team_id: 11 }, { encounter_team_id: 22 }] }]
    });
    getLogHistory.mockResolvedValue({
      items: [
        record(17, {
          status: "awaiting_link",
          teams: [
            { key: "alpha", source_position: 1, participants: [] },
            { key: "beta", source_position: 2, participants: [] }
          ]
        })
      ],
      total: 1
    });
    bindLogRecord.mockRejectedValue(new ApiError(409, [{ msg: "changed", code: "stale_revision" }]));
    const scope = await mount(78, [PLAYOFF]);
    await click(scope.querySelector('button[aria-label="Actions for round_17.txt"]'));
    await click(menuItem("Attach to game…"));
    await click(document.querySelector('button[aria-label="Pick an encounter"]'));
    await click(commandItem("Home vs Away"));
    await click(document.querySelector('button[aria-label="Pick a game"]'));
    await click(commandItem("Game 1 · Ilios · #801"));
    await click(document.querySelector('button[aria-label="Game team for log team alpha"]'));
    await click(commandItem("Home"));
    await click(document.querySelector('button[aria-label="Game team for log team beta"]'));
    await click(commandItem("Away"));
    const reads = getLogHistory.mock.calls.length;
    await click(button(document, "Bind and publish"));

    expect(notify.error).toHaveBeenCalledWith(
      expect.stringContaining("statistics changed"),
      expect.objectContaining({ description: "changed" })
    );
    expect(notify.success).not.toHaveBeenCalled();
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    await settle();
    expect(getLogHistory.mock.calls.length).toBeGreaterThan(reads);
  });

  it("never reads inherited properties as picked seats: keys `constructor` and `__proto__` need explicit, distinct seats", async () => {
    getEncounter.mockResolvedValue(SEATED);
    getLogHistory.mockResolvedValue({
      items: [
        record(17, {
          status: "awaiting_link",
          teams: [
            { key: "constructor", source_position: 1, participants: [] },
            { key: "__proto__", source_position: 2, participants: [] }
          ]
        })
      ],
      total: 1
    });
    bindLogRecord.mockResolvedValue({ id: 17, status: "done", error: null, binding: null });
    const scope = await mount(78, [PLAYOFF]);
    await click(scope.querySelector('button[aria-label="Actions for round_17.txt"]'));
    await click(menuItem("Attach to game…"));
    await click(document.querySelector('button[aria-label="Pick an encounter"]'));
    await click(commandItem("Home vs Away"));
    await click(document.querySelector('button[aria-label="Pick a game"]'));
    await click(commandItem("Game 1 · Ilios · #801"));
    expect(button(document, "Bind and publish")?.disabled).toBe(true);

    await click(document.querySelector('button[aria-label="Game team for log team constructor"]'));
    await click(commandItem("Away"));
    // The untouched `__proto__` picker must not count as a selection.
    expect(button(document, "Bind and publish")?.disabled).toBe(true);

    await click(document.querySelector('button[aria-label="Game team for log team __proto__"]'));
    await click(commandItem("Home"));
    await click(button(document, "Bind and publish"));

    const [, request] = bindLogRecord.mock.calls[0]!;
    const teams = request.teams as Record<string, number>;
    expect(Object.getOwnPropertyNames(teams).sort()).toEqual(["__proto__", "constructor"]);
    expect(Object.getOwnPropertyDescriptor(teams, "constructor")?.value).toBe(22);
    expect(Object.getOwnPropertyDescriptor(teams, "__proto__")?.value).toBe(11);
  });

  it("lets the workspace console bind a hintless job by picking tournament, encounter and game", async () => {
    getTournaments.mockResolvedValue({ results: [{ id: 78, name: "OWT 78" }] });
    getEncounters.mockResolvedValue({ results: [PLAYOFF] });
    getEncounter.mockResolvedValue(SEATED);
    getLogHistory.mockResolvedValue({
      items: [
        record(17, {
          status: "awaiting_link",
          tournament_id: null,
          tournament_name: null,
          teams: [
            { key: "alpha", source_position: 1, participants: [] },
            { key: "beta", source_position: 2, participants: [] }
          ]
        })
      ],
      total: 1
    });
    bindLogRecord.mockResolvedValue({ id: 17, status: "done", error: null, binding: null });
    // No encounter list is passed here, exactly as /admin/matches does.
    const scope = await mount(null, []);
    await click(scope.querySelector('button[aria-label="Actions for round_17.txt"]'));
    await click(menuItem("Attach to game…"));
    expect(document.querySelector('button[aria-label="Pick an encounter"]')?.hasAttribute("disabled")).toBe(true);
    await click(document.querySelector('button[aria-label="Pick a tournament"]'));
    await click(commandItem("OWT 78"));
    expect(getEncounters).toHaveBeenCalledWith(1, "", 78, -1, "id", "asc", 1);
    await click(document.querySelector('button[aria-label="Pick an encounter"]'));
    await click(commandItem("Home vs Away"));
    await click(document.querySelector('button[aria-label="Pick a game"]'));
    await click(commandItem("Game 1 · Ilios · #801"));
    await click(document.querySelector('button[aria-label="Game team for log team alpha"]'));
    await click(commandItem("Home"));
    await click(document.querySelector('button[aria-label="Game team for log team beta"]'));
    await click(commandItem("Away"));
    await click(button(document, "Bind and publish"));

    expect(bindLogRecord).toHaveBeenCalledWith(17, {
      encounter_game_id: 801,
      teams: { alpha: 11, beta: 22 },
      expected_revision: 0
    });
  });
});
