// @vitest-environment happy-dom
//
// Carried over from `TournamentSettingsTab.behavior.test` when the one
// "Integrations" card became two sections. What is pinned here:
//
//   1. the Challonge slug is a tournament field, so it saves through this
//      section's own bar — and through nothing else: Discord is not here;
//   2. no control in the section submits a form it happens to sit inside;
//   3. the unmapped-participant callout counts distinct PARTICIPANTS, not
//      failed rows, and routes to the mapping table that fixes them;
//   4. only the bracket is linked. A Challonge match or participant id has no
//      public URL, and rendering a link affordance around one goes nowhere.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Tournament } from "@/types/tournament.types";
import ChallongeSettingsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getTournament = vi.fn();
const getStages = vi.fn();
const updateTournament = vi.fn();
const setTournamentSchedule = vi.fn();
const challongeSyncLog = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getTournament: (...args: unknown[]) => getTournament(...args),
    getStages: (...args: unknown[]) => getStages(...args),
    updateTournament: (...args: unknown[]) => updateTournament(...args),
    setTournamentSchedule: (...args: unknown[]) => setTournamentSchedule(...args),
    challongeSyncLog: (...args: unknown[]) => challongeSyncLog(...args),
    challongeImport: vi.fn(),
    challongeExport: vi.fn()
  }
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "64" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() })
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  )
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isLoaded: true, canAccessPermission: () => true })
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), info: vi.fn(), apiError: vi.fn() }
}));

vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { workspaces: unknown[] }) => unknown) =>
    selector({ workspaces: [] })
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useFormatter: () => ({ dateTime: (value: Date) => value.toISOString() })
}));

const TOURNAMENT = {
  id: 64,
  workspace_id: 1,
  name: "OWT 64",
  slug: "owt-64",
  description: null,
  challonge_id: 991,
  challonge_slug: "owt-64",
  is_league: false,
  is_finished: false,
  is_hidden: false,
  team_formation: "balancer",
  status: "live",
  auto_transitions_enabled: true,
  allow_late_registration: false,
  phase_schedule: [],
  win_points: 3,
  draw_points: 1,
  loss_points: 0,
  stages: [],
  start_date: new Date("2026-04-18T00:00:00Z"),
  end_date: new Date("2026-04-19T00:00:00Z"),
  created_at: new Date("2026-01-01T00:00:00Z"),
  updated_at: null,
  participants_count: 20,
  registrations_count: 20,
  teams_count: 20,
  division_grid_version_id: null,
  division_grid_version: null
} as unknown as Tournament;

/** One failed import row per match, all blocked by the same two participants. */
function mappingFailure(id: number, participants: number[]) {
  return {
    id,
    created_at: "2026-08-25T18:18:00Z",
    source_id: 7,
    direction: "import",
    operation: "apply_import",
    entity_type: "match",
    entity_id: null,
    challonge_id: 463348963 + id,
    status: "failed",
    conflict_type: null,
    payload_json: { missing_participant_ids: participants },
    before_json: null,
    after_json: null,
    error_message: `Missing Challonge team mapping for participant(s): ${participants.join(", ")}`
  };
}

let container: HTMLDivElement;
let root: Root;

async function settle(times = 4) {
  for (let turn = 0; turn < times; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function render() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
      >
        <ChallongeSettingsPage />
      </QueryClientProvider>
    );
  });
  await settle();
}

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      globalThis.HTMLInputElement.prototype,
      "value"
    )?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
}

beforeEach(() => {
  getTournament.mockReset().mockResolvedValue(TOURNAMENT);
  getStages.mockReset().mockResolvedValue([]);
  updateTournament.mockReset().mockResolvedValue(TOURNAMENT);
  setTournamentSchedule.mockReset().mockResolvedValue(undefined);
  challongeSyncLog.mockReset().mockResolvedValue([]);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("Settings › Challonge", () => {
  it("keeps the link field with its sync controls, and nothing else", async () => {
    await render();

    expect(container.querySelector<HTMLInputElement>("#settings-challonge")?.value).toBe("owt-64");
    expect(container.textContent).toContain("Import");
    expect(container.textContent).toContain("Export");
    // Discord is its own section now: the two providers no longer share a card.
    expect(container.textContent).not.toContain("Discord match logs");
  });

  it("never lets a sync control submit a form it sits inside", async () => {
    await render();
    const buttons = [...container.querySelectorAll("button")];

    expect(buttons.length).toBeGreaterThan(0);
    expect(buttons.filter((button) => button.type !== "button")).toEqual([]);
  });

  it("saves the slug alone", async () => {
    await render();

    await type(container.querySelector<HTMLInputElement>("#settings-challonge")!, "owt-65");
    await act(async () => {
      [...document.querySelectorAll("button")]
        .find((button) => button.textContent?.trim() === "save")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(updateTournament).toHaveBeenCalledWith(64, { challonge_slug: "owt-65" });
    expect(setTournamentSchedule).not.toHaveBeenCalled();
  });

  it("counts distinct participants, not failed rows, and routes to the mapping table", async () => {
    challongeSyncLog.mockResolvedValue([
      mappingFailure(1, [298247245, 298247312]),
      mappingFailure(2, [298247312, 298247245]),
      mappingFailure(3, [298247245, 298247248])
    ]);
    await render();

    // Three failed rows, three overlapping pairs — but only three participants.
    expect(container.textContent).toContain("3 Challonge participants not mapped");
    const link = [...container.querySelectorAll("a")].find((anchor) =>
      anchor.textContent?.includes("Map teams")
    );
    expect(link?.getAttribute("href")).toBe("/admin/tournaments/64/teams/roster?challongeSync=1");
  });

  it("stays hidden when nothing failed for want of a mapping", async () => {
    challongeSyncLog.mockResolvedValue([
      { ...mappingFailure(1, []), status: "success", payload_json: null, error_message: null }
    ]);
    await render();

    expect(container.textContent).not.toContain("not mapped");
  });

  it("links the bracket itself, and leaves log ids as plain identifiers", async () => {
    challongeSyncLog.mockResolvedValue([mappingFailure(1, [298247245])]);
    await render();

    const anchors = [...container.querySelectorAll("a")];
    expect(
      anchors.find((anchor) => anchor.textContent?.includes("Open bracket"))?.getAttribute("href")
    ).toBe("https://challonge.com/owt-64");
    expect(anchors.some((anchor) => anchor.textContent?.includes("463348964"))).toBe(false);
    expect(container.textContent).toContain("463348964");
  });
});
