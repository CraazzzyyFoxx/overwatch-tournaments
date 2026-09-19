// @vitest-environment happy-dom
//
// The hub's Encounters view (P2-5). What is pinned here:
//  1. the `match.read` gate — the sub-tab bar is navigation, so the view itself
//     refuses, instead of the pre-redesign redirect that bounced an
//     unpermitted visitor to a sibling needing the very same grant;
//  2. `?stage=` narrows the list AND is the parameter the sibling views share;
//  3. `?id=` opens the inspector and is written by a row click;
//  4. one row action end to end: kebab → confirm → delete request.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Encounter } from "@/types/encounter.types";
import EncountersViewPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getAll = vi.fn();
const getTournament = vi.fn();
const getStages = vi.fn();
const getTeams = vi.fn();
const deleteEncounter = vi.fn();
const listEncounterReports = vi.fn();
const listAdminMatches = vi.fn();

let permitted = true;

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  // The Scheduled column formats through next-intl; the assertions below are
  // about WHICH instant a row carries, so the mock defers to plain `Intl`.
  useFormatter: () => ({
    dateTime: (date: Date, options?: Intl.DateTimeFormatOptions) =>
      new Intl.DateTimeFormat(undefined, options).format(date)
  }),
  NextIntlClientProvider: ({ children }: { children: ReactNode }) => children
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: (permission: string) =>
      permission === "match.read" ? permitted : permitted,
    isLoaded: true,
    isSuperuser: false
  })
}));

vi.mock("@/services/encounter.service", () => ({
  default: { getAll: (...args: unknown[]) => getAll(...args) }
}));
vi.mock("@/services/team.service", () => ({
  default: { getAll: (...args: unknown[]) => getTeams(...args) }
}));
vi.mock("@/services/tournament.service", () => ({
  default: { getAll: vi.fn().mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 }) }
}));
vi.mock("@/services/admin.service", () => ({
  default: {
    getTournament: (...args: unknown[]) => getTournament(...args),
    getStages: (...args: unknown[]) => getStages(...args),
    deleteEncounter: (...args: unknown[]) => deleteEncounter(...args),
    createEncounter: vi.fn(),
    updateEncounter: vi.fn(),
    syncEncountersFromChallonge: vi.fn(),
    listEncounterReports: (...args: unknown[]) => listEncounterReports(...args),
    listAdminMatches: (...args: unknown[]) => listAdminMatches(...args),
    uploadMatchLogs: vi.fn()
  }
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));
// The trail has its own behaviour suite and needs the layout's provider.
vi.mock("@/components/kit/AuditTrailSheet", () => ({
  AuditTrailButton: () => <button type="button">Change history</button>
}));

const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});

let rerender: (() => void) | null = null;

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "78" }),
  usePathname: () => "/admin/tournaments/78/matches/encounters",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

function encounter(overrides: Partial<Encounter> = {}): Encounter {
  return {
    id: 8812,
    created_at: new Date("2026-05-01T00:00:00Z"),
    updated_at: null,
    name: "Team C vs Team D",
    home_team_id: 3,
    away_team_id: 4,
    score: { home: 0, away: 0 },
    round: 3,
    best_of: 3,
    tournament_id: 78,
    stage_id: 5,
    stage_item_id: null,
    challonge_id: null,
    status: "PENDING",
    closeness: null,
    has_logs: false,
    result_status: "none",
    scheduled_at: null,
    started_at: null,
    ended_at: null,
    current_map_index: null,
    confirmed_at: null,
    matches: [],
    home_team: { id: 3, name: "Team C" } as Encounter["home_team"],
    away_team: { id: 4, name: "Team D" } as Encounter["away_team"],
    tournament: { id: 78, name: "OWT 78" } as Encounter["tournament"],
    stage: { id: 5, name: "Groups" } as Encounter["stage"],
    stage_item: null,
    ...overrides
  };
}

const mounted: { root: Root; container: HTMLElement }[] = [];

async function settle(turns = 8, delayMs = 0) {
  for (let turn = 0; turn < turns; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, delayMs);
      await promise;
    });
  }
}

function Harness({ render }: Readonly<{ render: () => ReactNode }>) {
  const [, force] = useState(0);
  // Published from an effect, not during render: writing a module-scope binding
  // while rendering is a side effect the react-compiler rules reject.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <>{render()}</>;
}

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        {/* The admin layout mounts this once; StatusIcon's tooltip needs it. */}
        <TooltipProvider>
          <Harness render={() => <EncountersViewPage />} />
        </TooltipProvider>
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
  await settle(3);
}

/**
 * Polls with a real delay: the view is code-split, so the first assertion in
 * the file waits on a dynamic import as well as on React Query, and a burst of
 * zero-delay turns spins past it in under a millisecond.
 */
async function waitFor<T>(read: () => T | null | undefined | false, what: string): Promise<T> {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const value = read();
    if (value) return value as T;
    await settle(1, 25);
  }
  throw new Error(`timed out waiting for ${what}`);
}

function button(text: string) {
  return Array.from(document.querySelectorAll("button")).find(
    (element) => element.textContent?.trim() === text
  );
}

function menuItem(text: string) {
  return Array.from(document.querySelectorAll('[role="menuitem"]')).find(
    (element) => element.textContent?.trim() === text
  );
}

function commandItem(label: string) {
  return Array.from(document.querySelectorAll('[cmdk-item=""]')).find(
    (item) => item.textContent?.trim().startsWith(label)
  );
}

function lastListCall() {
  return getAll.mock.calls.at(-1)!;
}

beforeEach(() => {
  permitted = true;
  replace.mockClear();
  getAll.mockReset().mockResolvedValue({
    results: [encounter()],
    total: 1,
    page: 1,
    per_page: 15
  });
  getTournament.mockReset().mockResolvedValue({
    id: 78,
    name: "OWT 78",
    workspace_id: 1,
    challonge_slug: null
  });
  getStages.mockReset().mockResolvedValue([{ id: 5, name: "Groups", order: 1, items: [] }]);
  getTeams.mockReset().mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });
  deleteEncounter.mockReset().mockResolvedValue(undefined);
  listEncounterReports.mockReset().mockResolvedValue({
    results: [],
    total: 0,
    page: 1,
    per_page: 25
  });
  listAdminMatches.mockReset().mockResolvedValue({ results: [], total: 0, page: 1, per_page: 25 });
  window.history.replaceState(null, "", "/admin/tournaments/78/matches/encounters");
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

describe("hub Matches › Encounters", () => {
  it("refuses without match.read instead of bouncing to a sibling view", async () => {
    permitted = false;
    const container = await mount();

    expect(container.textContent).toContain("Unauthorized");
    expect(getAll).not.toHaveBeenCalled();
    // No redirect: the sub-tab bar cannot offer a view this caller may open.
    expect(replace).not.toHaveBeenCalled();
  });

  it("lists the tournament's encounters and pins the tournament chip", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("Team C vs Team D"), "the encounter row");

    expect(lastListCall()[2]).toBe(78);
    const pinned = container.querySelector('[data-pinned-filter="tournament"]');
    expect(pinned?.textContent).toContain("OWT 78");
  });

  it("sends ?stage= to the endpoint as stage_id and keeps it in the URL", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("Team C vs Team D"), "the encounter row");

    await click(container.querySelector('button[aria-label="Add filter"]'));
    await click(await waitFor(() => commandItem("Stage"), "the Stage filter"));
    await click(await waitFor(() => commandItem("Groups"), "the Groups option"));

    // The shared scope parameter: the sub-tab bar carries this exact key over
    // to Standings, Reports and Parsed maps.
    expect(new URLSearchParams(window.location.search).get("stage")).toBe("5");
    await waitFor(() => lastListCall()[7]?.stage_id === 5, "the scoped list request");
  });

  it("restores ?stage= from the URL on load", async () => {
    window.history.replaceState(
      null,
      "",
      "/admin/tournaments/78/matches/encounters?stage=5"
    );
    await mount();

    await waitFor(() => lastListCall()[7]?.stage_id === 5, "the scoped list request");
  });

  it("opens the inspector for the clicked row and writes ?id=", async () => {
    const container = await mount();
    const row = await waitFor(
      () => container.querySelector("tbody tr[tabindex]"),
      "the first data row"
    );

    await click(row);

    expect(new URLSearchParams(window.location.search).get("id")).toBe("8812");
    const inspector = await waitFor(
      () => document.querySelector('aside[aria-label="Row inspector"], [role="dialog"]'),
      "the inspector"
    );
    expect(inspector.textContent).toContain("Encounter #8812");
    // The entity actions live in the inspector header, not in every table row.
    expect(button("Upload log")).toBeTruthy();
  });

  it("deletes an encounter from the row kebab through one confirmation", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("Team C vs Team D"), "the encounter row");

    await click(
      container.querySelector('button[aria-label="Actions for Team C vs Team D"]')
    );
    await click(await waitFor(() => menuItem("Delete encounter"), "the delete action"));

    // One ConfirmDialog with an intent, not a per-entity dialog mount.
    expect(document.body.textContent).toContain("Delete encounter");
    await click(await waitFor(() => button("Delete encounter"), "the confirm button"));

    expect(deleteEncounter).toHaveBeenCalledWith(8812);
  });

  // The planned start time (P7): entered per round in the stage editor, or per
  // match in the match editor. Invisible here before this column, so an
  // organizer could not tell which matches had a time at all.
  it("shows the planned start time, and an em dash for a match without one", async () => {
    getAll.mockResolvedValue({
      results: [
        encounter(),
        encounter({ id: 8813, name: "Team E vs Team F", scheduled_at: "2026-05-02T15:00:00.000Z" })
      ],
      total: 2,
      page: 1,
      per_page: 15
    });
    const container = await mount();
    await waitFor(() => container.textContent?.includes("Team E vs Team F"), "the encounter rows");

    const headers = [...container.querySelectorAll("thead th")];
    const column = headers.findIndex((th) => (th.textContent ?? "").trim() === "Scheduled");
    expect(column).toBeGreaterThan(-1);

    const cells = [...container.querySelectorAll("tbody tr")].map(
      (row) => row.querySelectorAll("td")[column]
    );
    // Machine-readable instant, so the rendered text can stay short and local.
    expect(cells[1]?.querySelector("time")?.getAttribute("dateTime")).toBe(
      "2026-05-02T15:00:00.000Z"
    );
    expect(cells[1]?.textContent?.trim()).not.toBe("");
    expect(cells[0]?.textContent?.trim()).toBe("—");
  });
});
