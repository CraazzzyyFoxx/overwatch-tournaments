// @vitest-environment happy-dom
//
// The Round schedule section on an FFA stage.
//
// The section read `encounterService.getAll`, which answers DUELS — an FFA
// stage's lobbies are never in that list. So a stage with two generated lobbies
// reported "No lobbies in this stage yet" and their kickoff time could not be
// authored at all, on any screen. The lobbies are read from the stage's own FFA
// endpoint instead, as the one round they are.
//
// What is pinned here:
//  1. an FFA stage offers exactly ONE row, covering every lobby of the stage;
//  2. Apply writes `scheduled_at` to every lobby — one PATCH each, and nothing
//     but that field, which is all `_FFA_EDITABLE_FIELDS` accepts;
//  3. the lobby reads are refreshed afterwards, or the panel and the lobby page
//     keep printing the old kickoff.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { zonedInputToUtc } from "@/lib/workspace/timezone";
import type { EncounterUpdateInput } from "@/types/admin.types";
import type { FfaLobby } from "@/types/ffa.types";
import type { Stage } from "@/types/tournament.types";

import BracketTabPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getStages = vi.fn();
const getTournament = vi.fn();
const getStagesProgress = vi.fn();
const getTeams = vi.fn();
const getEncounters = vi.fn();
const updateEncounter = vi.fn();
const getFfaStage = vi.fn();
const invalidateWorkspace = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getStages: (...args: unknown[]) => getStages(...args),
    getTournament: (...args: unknown[]) => getTournament(...args),
    getStagesProgress: (...args: unknown[]) => getStagesProgress(...args),
    updateEncounter: (...args: unknown[]) => updateEncounter(...args),
    updateStage: vi.fn()
  }
}));

vi.mock("@/services/team.service", () => ({
  default: { getAll: (...args: unknown[]) => getTeams(...args) }
}));

vi.mock("@/services/encounter.service", () => ({
  default: { getAll: (...args: unknown[]) => getEncounters(...args) }
}));

vi.mock("@/services/ffa.service", () => ({
  default: { getStage: (...args: unknown[]) => getFfaStage(...args) }
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isSuperuser: true })
}));

vi.mock("@/hooks/useMobile", () => ({ useIsMobile: () => false }));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/tournaments/84/bracket",
  useParams: () => ({ id: "84" }),
  useSearchParams: () => new URLSearchParams("stage=10&section=schedule")
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: unknown }) => (
    <a href={href} {...rest}>
      {children as never}
    </a>
  )
}));

// Partial: the section's query reads the real key factory from this module.
vi.mock("@/lib/tournament/workspace-query-keys", async (importOriginal) => ({
  ...((await importOriginal()) as object),
  invalidateTournamentWorkspace: (...args: unknown[]) => invalidateWorkspace(...args)
}));

/** An FFA league with two groups, each holding one lobby. */
function ffaStage(): Stage {
  return {
    id: 10,
    tournament_id: 84,
    name: "FFA League",
    description: null,
    stage_type: "ffa_league",
    max_rounds: 1,
    advance_count: 2,
    split_lower_bracket: false,
    order: 0,
    is_active: true,
    is_published: true,
    is_completed: false,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: { win: null, draw: null, loss: null },
    swiss_bye_points: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 3, by_round: {}, final: null },
    ffa_scoring: { placement_points: [], score_points: 1, score_label: null },
    challonge_id: null,
    challonge_slug: null,
    items: [
      { id: 100, stage_id: 10, name: "Group A", type: "group", order: 0, inputs: [] },
      { id: 101, stage_id: 10, name: "Group B", type: "group", order: 1, inputs: [] }
    ]
  } as unknown as Stage;
}

function lobby(encounterId: number, stageItemId: number, scheduledAt: string | null): FfaLobby {
  return {
    encounter_id: encounterId,
    tournament_id: 84,
    stage_id: 10,
    stage_item_id: stageItemId,
    name: `Lobby ${encounterId}`,
    status: "open",
    result_status: "none",
    best_of: 3,
    scheduled_at: scheduledAt,
    advance_count: 2,
    rules: { placement_points: [10, 6, 3], score_points: 1, score_label: null },
    rows: []
  };
}

const VIEWER_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

let container: HTMLDivElement;
let root: Root;

async function settle(times = 12) {
  for (let index = 0; index < times; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount(lobbies: FfaLobby[]) {
  getStages.mockResolvedValue([ffaStage()]);
  getTournament.mockResolvedValue({ id: 84, name: "Cup" });
  getStagesProgress.mockResolvedValue([{ stage_id: 10, total: 2, completed: 0 }]);
  getTeams.mockResolvedValue({ results: [] });
  // The duel list the section used to read: an FFA stage is simply absent here.
  getEncounters.mockResolvedValue({ results: [], total: 0 });
  getFfaStage.mockResolvedValue(lobbies);

  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
          <BracketTabPage />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
}

async function click(element: Element | null | undefined) {
  if (!element) throw new Error("nothing to click");
  await act(async () => {
    element.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    (element as HTMLElement).click();
  });
  await settle(4);
}

/** The `sr-only` labels naming each row's date trigger — one per row. */
function rowLabels(): string[] {
  return [...container.querySelectorAll<HTMLLabelElement>("label")]
    .map((element) => element.textContent ?? "")
    .filter((text) => text.startsWith("Start time for "))
    .map((text) => text.replace("Start time for ", ""));
}

function scheduleRow(label: string): HTMLTableRowElement {
  const found = [...container.querySelectorAll<HTMLLabelElement>("label")]
    .find((element) => element.textContent === `Start time for ${label}`)
    ?.closest("tr");
  if (!(found instanceof HTMLTableRowElement)) throw new Error(`no row for "${label}"`);
  return found;
}

/** Types into a controlled input the way React hears it. */
async function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
}

/** Today on the viewer's clock — the day an empty picker adopts. */
function todayAt(time: string): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${time}`;
}

beforeEach(() => {
  vi.clearAllMocks();
  if (root) {
    act(() => root.unmount());
    container.remove();
  }
  updateEncounter.mockResolvedValue(undefined);
});

describe("Stage editor round schedule on an FFA stage", () => {
  it("offers one row covering every lobby of the stage", async () => {
    await mount([lobby(41, 100, null), lobby(42, 101, null)]);

    expect(getFfaStage).toHaveBeenCalledWith(84, 10);
    // One round, not one row per group: every lobby of the stage starts together.
    expect(rowLabels()).toEqual(["Lobbies"]);
    expect(scheduleRow("Lobbies").textContent).toContain("2");
    // The count column is named after what it counts.
    expect(
      [...container.querySelectorAll("th")].map((node) => node.textContent)
    ).toContain("Lobbies");
  });

  it("writes the chosen time to every lobby, one request each, and nothing else", async () => {
    await mount([lobby(41, 100, null), lobby(42, 101, null)]);

    const input = scheduleRow("Lobbies").querySelector("input");
    await type(input as HTMLInputElement, "19:30");
    const apply = [...scheduleRow("Lobbies").querySelectorAll("button")].find(
      (element) => (element.textContent ?? "").trim() === "Apply"
    );
    await click(apply);

    const expected = zonedInputToUtc(todayAt("19:30"), VIEWER_ZONE);
    const calls = updateEncounter.mock.calls as [number, EncounterUpdateInput][];
    expect(calls.map(([id]) => id)).toEqual([41, 42]);
    // `_FFA_EDITABLE_FIELDS` accepts `scheduled_at` and nothing more, so the
    // payload carries exactly that.
    expect(calls.map(([, payload]) => payload)).toEqual([
      { scheduled_at: expected },
      { scheduled_at: expected }
    ]);
    // The public bracket and the lobby page read the lobbies, not the duel list.
    expect(invalidateWorkspace).toHaveBeenCalled();
    expect(getFfaStage).toHaveBeenCalledTimes(2);
  });

  it("says lobbies, not matches, when the stage has none yet", async () => {
    await mount([]);

    expect(container.textContent).toContain("No lobbies in this stage yet");
    expect(container.textContent).not.toContain("No matches in this stage yet");
  });
});
