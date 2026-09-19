// @vitest-environment happy-dom
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EncounterReportsBrowser } from "@/components/admin/EncounterReportsBrowser";
import type {
  AdminCaptainReport,
  EncounterReportsQuery,
  EncounterReportsRow
} from "@/types/admin.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listEncounterReports = vi.fn();
const getEncounterReportStats = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    listEncounterReports: (...args: unknown[]) => listEncounterReports(...args),
    getEncounterReportStats: (...args: unknown[]) => getEncounterReportStats(...args),
    getStages: vi.fn().mockResolvedValue([])
  }
}));

vi.mock("@/services/tournament.service", () => ({
  default: { getAll: vi.fn().mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 }) }
}));

const getReportForm = vi.fn();

vi.mock("@/services/report-form.service", () => ({
  default: { getReportForm: (...args: unknown[]) => getReportForm(...args) }
}));

/**
 * `router.replace` in the app writes the URL and re-renders from the new
 * `useSearchParams`; here it writes `window.history` and pokes the harness, so
 * a chip really does travel through the query string.
 */
const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});

let rerender: (() => void) | null = null;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/matches",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

vi.mock("@/lib/tournament-workspace-query-keys", () => ({
  invalidateTournamentWorkspace: vi.fn()
}));

// The resolve dialog has its own behaviour suite; here it only has to report
// whether the browser handed it a row.
vi.mock("@/components/admin/ResolveResultDialog", () => ({
  ResolveResultDialog: ({ open, row }: { open: boolean; row: EncounterReportsRow | null }) =>
    open ? <div data-testid="resolve">{row?.name}</div> : null
}));

async function tick() {
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
}

async function waitFor<T>(read: () => T | null | undefined | false, what: string): Promise<T> {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const value = read();
    if (value) return value as T;
    await tick();
  }
  throw new Error(`timed out waiting for ${what}`);
}

/**
 * Renders through a factory, not a stored element: React bails out of
 * re-rendering a child whose element is referentially identical, so a
 * URL-driven re-render would never reach the browser under test.
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

async function mount(render: () => ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <Harness render={render} />
      </QueryClientProvider>
    );
  });
  await tick();
  return container;
}

async function click(element: Element | null | undefined) {
  expect(element).toBeTruthy();
  await act(async () => {
    (element as HTMLElement).dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await tick();
}

function button(scope: ParentNode, text: string) {
  return Array.from(scope.querySelectorAll("button")).find(
    (element) => element.textContent?.trim() === text
  );
}

/** Chip options render into a portal on `document.body`, not the container. */
function commandItem(label: string) {
  return Array.from(document.querySelectorAll('[cmdk-item=""]')).find(
    (item) => item.textContent?.trim().startsWith(label)
  );
}

/** Open the "+ Filter" popover and pick `filter › option`. */
async function pickChip(scope: ParentNode, filter: string, option?: string) {
  await click(scope.querySelector('button[aria-label="Add filter"]'));
  await click(await waitFor(() => commandItem(filter), `the ${filter} filter`));
  if (option) {
    await click(await waitFor(() => commandItem(option), `the ${option} option`));
  }
}

function activeChip(label: string) {
  return document.querySelector<HTMLButtonElement>(`button[aria-label="Remove filter ${label}"]`);
}

function dataRows(scope: ParentNode) {
  return Array.from(scope.querySelectorAll("tbody tr"));
}

function bodyText(scope: ParentNode) {
  return scope.querySelector("tbody")?.textContent ?? "";
}

function lastQuery(): EncounterReportsQuery {
  return listEncounterReports.mock.calls.at(-1)![0] as EncounterReportsQuery;
}

function report(overrides: Partial<AdminCaptainReport> = {}): AdminCaptainReport {
  return {
    id: 1,
    encounter_id: 11,
    team_id: 1,
    side: "home",
    reporter_user_id: 5,
    reporter_name: "captain-alpha",
    home_score: 3,
    away_score: 1,
    closeness: 4,
    map_codes: [],
    comment: null,
    custom_fields: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    ...overrides
  };
}

function row(overrides: Partial<EncounterReportsRow> = {}): EncounterReportsRow {
  return {
    id: 11,
    name: "Alpha vs Beta",
    tournament_id: 3,
    tournament_name: "Spring Cup",
    stage_name: "Group A",
    stage_type: "round_robin",
    round: 2,
    best_of: 3,
    status: "completed",
    result_status: "disputed",
    scheduled_at: null,
    home_team: { id: 1, name: "Alpha" },
    away_team: { id: 2, name: "Beta" },
    home_report: report(),
    away_report: report({ id: 2, side: "away", home_score: 1, away_score: 3 }),
    reported_count: 2,
    scores_match: false,
    series_score_valid: true,
    last_resolution: null,
    ...overrides
  };
}

function pageOf(results: EncounterReportsRow[], total = results.length) {
  return { results, total, page: 1, per_page: 25 };
}

describe("EncounterReportsBrowser", () => {
  beforeEach(() => {
    listEncounterReports.mockReset();
    getEncounterReportStats.mockReset();
    getReportForm.mockReset();
    getReportForm.mockResolvedValue({
      tournament_id: 7,
      built_in_fields: {
        closeness: { enabled: true, required: true },
        map_codes: { enabled: true, required: false },
        comment: { enabled: true, required: false }
      },
      custom_fields: [
        { key: "vod", label: "VOD link", type: "text", required: false, placeholder: null }
      ]
    });
    listEncounterReports.mockResolvedValue(pageOf([row()]));
    getEncounterReportStats.mockResolvedValue({
      by_result_status: { confirmed: 7, disputed: 2 },
      mismatch_count: 3,
      awaiting_second_count: 1
    });
    replace.mockClear();
    window.history.replaceState(null, "", "/admin/matches");
    document.body.innerHTML = "";
  });

  it("renders each encounter and both captains' reports through the shared table", async () => {
    const container = await mount(() => (
      <EncounterReportsBrowser tournamentId={null} workspaceId={4} canUpdateEncounter />
    ));
    await waitFor(() => bodyText(container).includes("Alpha vs Beta"), "the encounter row");

    expect(container.querySelector("table")).toBeTruthy();
    const text = bodyText(container);
    expect(text).toContain("Spring Cup");
    expect(text).toContain("Group A");
    expect(text).toContain("Round 2");
    // The three-valued verdict, in the row rather than only in a dialog.
    expect(text).toContain("Reports disagree");
    expect(text).toContain("captain-alpha");
  });

  it("sends each chip to the endpoint under its own query param", async () => {
    const container = await mount(() => (
      <EncounterReportsBrowser tournamentId={null} workspaceId={4} canUpdateEncounter />
    ));
    await waitFor(() => listEncounterReports.mock.calls.length > 0, "the list request");

    await pickChip(container, "Result", "Disputed");
    expect(lastQuery().result_status).toEqual(["disputed"]);
    // The param is the endpoint's own name, not one the table invented, and it
    // survives in the URL so a narrowed list is linkable.
    expect(new URLSearchParams(window.location.search).get("result_status")).toBe("disputed");

    await pickChip(container, "Reports filed", "Awaiting second");
    expect(lastQuery().reported_count).toBe(1);
    // Two chips, two params: narrowing one must not silently drop the other.
    expect(lastQuery().result_status).toEqual(["disputed"]);

    // Zero is a value, not "unset" — "nobody reported" is the whole point of
    // this option and a falsy guard would swallow it.
    await pickChip(container, "Reports filed", "No reports");
    expect(lastQuery().reported_count).toBe(0);

    // Removing the chips is how "all" is spelled.
    await click(activeChip("Reports filed: No reports"));
    await click(activeChip("Result: Disputed"));
    expect(lastQuery().reported_count).toBeUndefined();
    expect(lastQuery().result_status).toBeUndefined();
  });

  it("keeps the disagreement filter its own chip, because it is its own param", async () => {
    const container = await mount(() => (
      <EncounterReportsBrowser tournamentId={null} workspaceId={4} canUpdateEncounter />
    ));
    await waitFor(() => listEncounterReports.mock.calls.length > 0, "the list request");

    await pickChip(container, "Reports disagree");

    expect(lastQuery().mismatch_only).toBe(true);
    expect(activeChip("Reports disagree")).not.toBeNull();

    await click(activeChip("Reports disagree"));

    // Off is "no filter", not "reports agree": `mismatch_only=false` selects
    // nothing on the server, so sending it would be a lie.
    expect(lastQuery().mismatch_only).toBeUndefined();
  });

  it("keeps the counters on the scope, so filters do not move the numbers", async () => {
    const container = await mount(() => (
      <EncounterReportsBrowser tournamentId={7} workspaceId={4} canUpdateEncounter />
    ));
    await waitFor(() => getEncounterReportStats.mock.calls.length > 0, "the stats request");

    const scope = getEncounterReportStats.mock.calls[0][0] as EncounterReportsQuery;
    expect(scope.workspace_id).toBe(4);
    expect(scope.tournament_id).toBe(7);
    // A counter narrowed by the current filter would report what is already on
    // screen instead of how much the scope still has to settle.
    expect(scope.result_status).toBeUndefined();
    expect(scope.mismatch_only).toBeUndefined();
    expect(scope.query).toBeUndefined();

    await pickChip(container, "Result", "Disputed");
    await pickChip(container, "Reports disagree");

    expect(getEncounterReportStats).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("Reports disagree");
  });

  it("opens the inspector for the clicked row, and resolves from there", async () => {
    const container = await mount(() => (
      <EncounterReportsBrowser tournamentId={null} workspaceId={4} canUpdateEncounter />
    ));
    const first = await waitFor(
      () => (bodyText(container).includes("Alpha vs Beta") ? dataRows(container)[0] : null),
      "the first data row"
    );
    expect(container.querySelector('[data-testid="resolve"]')).toBeNull();

    await click(first);

    // The row opens detail, not a dialog: the write surface is one deliberate
    // action inside the inspector rather than a click away from the list.
    expect(new URLSearchParams(window.location.search).get("id")).toBe("11");
    const inspector = await waitFor(
      () => container.querySelector('aside[aria-label="Row inspector"], [role="dialog"]'),
      "the inspector"
    );
    expect(inspector.textContent).toContain("Alpha vs Beta");

    await click(button(container, "Resolve result"));
    expect(container.querySelector('[data-testid="resolve"]')?.textContent).toBe("Alpha vs Beta");
  });

  it("gives match closeness its own column, sighted without opening a row", async () => {
    listEncounterReports.mockResolvedValue(
      pageOf([
        row({
          home_report: report({ closeness: 9 }),
          away_report: report({ id: 2, side: "away", closeness: 2 })
        })
      ])
    );
    const container = await mount(() => (
      <EncounterReportsBrowser tournamentId={7} workspaceId={4} canUpdateEncounter />
    ));
    await waitFor(() => bodyText(container).includes("Alpha vs Beta"), "the encounter row");

    const headers = Array.from(container.querySelectorAll("thead th")).map(
      (cell) => cell.textContent ?? ""
    );
    expect(headers.some((text) => text.includes("Closeness"))).toBe(true);

    // Both sides: one captain calling a stomp and the other a nailbiter is the
    // signal, and a single averaged number would erase it.
    const cell = Array.from(container.querySelectorAll("tbody td")).find((td) =>
      (td.textContent ?? "").includes("9/10")
    );
    expect(cell?.textContent).toContain("2/10");

    // The picker is what makes the rest of the fields reachable at all.
    expect(button(container, "Columns")).toBeTruthy();
  });

  it("opens the whole filing, including the organizer's own questions", async () => {
    listEncounterReports.mockResolvedValue(
      pageOf([
        row({
          home_report: report({
            comment: "they left early",
            map_codes: [{ id: 1, map_index: 1, map_id: null, code: "B2C3" }],
            custom_fields: { vod: "https://twitch.tv/clip" }
          }),
          away_report: null,
          reported_count: 1,
          scores_match: null
        })
      ])
    );
    window.history.replaceState(null, "", "/admin/matches?id=11");
    const container = await mount(() => (
      <EncounterReportsBrowser tournamentId={7} workspaceId={4} canUpdateEncounter />
    ));
    const inspector = await waitFor(
      () => container.querySelector('aside[aria-label="Row inspector"], [role="dialog"]'),
      "the inspector"
    );
    await waitFor(() => inspector.textContent?.includes("VOD link"), "the custom field label");

    const text = inspector.textContent ?? "";
    // Everything the captain filed, so nothing has to be looked up elsewhere.
    expect(text).toContain("they left early");
    expect(text).toContain("M2 B2C3");
    expect(text).toContain("https://twitch.tv/clip");
    // A side that filed nothing is said so, not left as a silent gap.
    expect(text).toContain("No report filed.");
  });

  it("labels an already confirmed result Review rather than Resolve", async () => {
    listEncounterReports.mockResolvedValue(
      pageOf([row({ result_status: "confirmed", scores_match: true })])
    );
    window.history.replaceState(null, "", "/admin/matches?id=11");
    const container = await mount(() => (
      <EncounterReportsBrowser tournamentId={null} workspaceId={4} canUpdateEncounter />
    ));
    await waitFor(() => button(container, "Review result"), "the review action");

    expect(button(container, "Resolve result")).toBeUndefined();
  });

  it("withholds the write surface from an admin who may not update encounters", async () => {
    window.history.replaceState(null, "", "/admin/matches?id=11");
    const container = await mount(() => (
      <EncounterReportsBrowser tournamentId={null} workspaceId={4} canUpdateEncounter={false} />
    ));
    await waitFor(() => bodyText(container).includes("Alpha vs Beta"), "the encounter row");

    // The inspector still opens — reading a dispute is not writing one — but it
    // offers no action it cannot carry out.
    expect(button(container, "Resolve result")).toBeUndefined();
    expect(button(container, "Review result")).toBeUndefined();
  });

  it("asks for nothing until a workspace is chosen", async () => {
    const container = await mount(() => (
      <EncounterReportsBrowser tournamentId={null} workspaceId={null} canUpdateEncounter />
    ));

    expect(listEncounterReports).not.toHaveBeenCalled();
    expect(getEncounterReportStats).not.toHaveBeenCalled();
    expect(container.textContent).toContain("scoped to a workspace");
  });
});
