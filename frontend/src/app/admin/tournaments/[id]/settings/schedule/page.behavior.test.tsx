// @vitest-environment happy-dom
//
// Carried over from `TournamentSettingsTab.behavior.test`: the late-registration
// override spent a release editable only through the raw admin API, so what is
// pinned is that it has a control, a label a screen reader can read, a payload
// that carries it — and a warning when it would change nothing.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Tournament } from "@/types/tournament.types";
import ScheduleSettingsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getTournament = vi.fn();
const updateTournament = vi.fn();
const setTournamentSchedule = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getTournament: (...args: unknown[]) => getTournament(...args),
    updateTournament: (...args: unknown[]) => updateTournament(...args),
    setTournamentSchedule: (...args: unknown[]) => setTournamentSchedule(...args)
  }
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "64" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() })
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
  useLocale: () => "en",
  // The schedule section renders DateRangePicker, which formats through
  // next-intl rather than a pinned locale.
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({
    dateTime: (value: Date, options?: Intl.DateTimeFormatOptions) =>
      new Intl.DateTimeFormat("en", options).format(value),
    number: (value: number, options?: Intl.NumberFormatOptions) =>
      new Intl.NumberFormat("en", options).format(value)
  })
}));

const TOURNAMENT = {
  id: 64,
  workspace_id: 1,
  name: "OWT 64",
  slug: "owt-64",
  description: null,
  challonge_id: null,
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
        <ScheduleSettingsPage />
      </QueryClientProvider>
    );
  });
  await settle();
}

function toggle() {
  const node = container.querySelector("#settings-allow-late-registration");
  if (!node) throw new Error("late-registration toggle not rendered");
  return node;
}

beforeEach(() => {
  getTournament.mockReset().mockResolvedValue(TOURNAMENT);
  updateTournament.mockReset().mockResolvedValue(TOURNAMENT);
  setTournamentSchedule.mockReset().mockResolvedValue(undefined);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("Settings › Schedule", () => {
  it("labels the late-registration override and reaches the update payload", async () => {
    await render();

    expect(
      container.querySelector("label[for='settings-allow-late-registration']")?.textContent
    ).toBe("Allow late registration");
    expect(toggle().getAttribute("aria-checked")).toBe("false");

    await act(async () => {
      toggle().dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();
    expect(toggle().getAttribute("aria-checked")).toBe("true");

    await act(async () => {
      [...document.querySelectorAll("button")]
        .find((button) => button.textContent?.trim() === "save")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(updateTournament).toHaveBeenCalledWith(64, { allow_late_registration: true });
    // The phase schedule is untouched, so its own endpoint is left alone.
    expect(setTournamentSchedule).not.toHaveBeenCalled();
  });

  it("warns that it is a no-op while the registration window is open-ended", async () => {
    // `phase_schedule` is empty, so the registration row carries no `ends_at` —
    // there is nothing for the override to lift, and saying so is the point: a
    // switch that appears to do nothing is what this feature was before.
    await render();

    expect(container.textContent).toContain("this changes nothing");
  });
});
