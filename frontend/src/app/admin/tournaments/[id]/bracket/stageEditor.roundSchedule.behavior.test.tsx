// @vitest-environment happy-dom
//
// The stage editor's Round schedule section (P7, wireframes §7 DATA box).
//
// A match carried only a round number; organizers published times in Discord
// and the public page could not group matches by day. The minimal model is one
// planned time per ROUND — because a round is what an organizer schedules —
// with a per-match override in the match editor for the one series that moved.
//
// What is pinned here:
//  1. the rows are the rounds the stage's MATCHES carry, named the way the
//     bracket names them (a lower-bracket round is "LB Round 1", not "-1"), and
//     another stage's matches never leak in;
//  2. Apply writes the chosen time to every match of that round — one PATCH per
//     match — and refreshes the views that render it;
//  3. a match moved on its own is not silently overwritten: applying its round
//     asks first. Confirming overwrites it; cancelling keeps it and still
//     schedules the rest, which is the whole point of the question.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { utcToZonedInput, zonedInputToUtc } from "@/lib/workspace/timezone";
import type { EncounterUpdateInput } from "@/types/admin.types";
import type { Encounter } from "@/types/encounter.types";
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

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isSuperuser: true })
}));

vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => false }));

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

/** An 8-team double elimination: upper rounds 1..3, lower -1..-4. */
function playoffStage(): Stage {
  return {
    id: 10,
    tournament_id: 84,
    name: "Playoff",
    description: null,
    stage_type: "double_elimination",
    max_rounds: 4,
    advance_count: null,
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
      {
        id: 100,
        stage_id: 10,
        name: "Bracket",
        type: "single_bracket",
        order: 0,
        inputs: Array.from({ length: 8 }, (_, index) => ({
          id: 200 + index,
          stage_item_id: 100,
          slot: index + 1,
          input_type: "final",
          team_id: index + 1,
          winner_from_stage_item_id: null,
          winner_position: null,
          team: null
        }))
      }
    ]
  } as unknown as Stage;
}

function encounter(
  id: number,
  round: number,
  scheduledAt: string | null,
  stageId = 10
): Encounter {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name: `Match ${id}`,
    home_team_id: 1,
    away_team_id: 2,
    score: { home: 0, away: 0 },
    round,
    best_of: 3,
    tournament_id: 84,
    stage_id: stageId,
    stage_item_id: 100,
    challonge_id: null,
    status: "open",
    closeness: null,
    has_logs: false,
    result_status: "none",
    scheduled_at: scheduledAt,
    started_at: null,
    ended_at: null,
    current_map_index: null,
    confirmed_at: null,
    matches: [],
    home_team: { id: 1, name: "Alpha" } as Encounter["home_team"],
    away_team: { id: 2, name: "Bravo" } as Encounter["away_team"],
    tournament: { id: 84, name: "Cup" } as Encounter["tournament"],
    stage: null,
    stage_item: null
  };
}

/**
 * Round 1: four unscheduled matches. Round 2: two matches sharing 15:00 UTC
 * except #6, which was moved to 18:00 — the individual override. Round -1: the
 * lower bracket, so the labels have to be signed. The last row belongs to
 * ANOTHER stage and must not appear.
 */
const ENCOUNTERS = [
  encounter(1, 1, null),
  encounter(2, 1, null),
  encounter(3, 1, null),
  encounter(4, 1, null),
  encounter(5, 2, "2026-05-02T15:00:00.000Z"),
  encounter(6, 2, "2026-05-02T18:00:00.000Z"),
  encounter(7, -1, null),
  encounter(8, 1, null, 20)
];

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

async function mount() {
  getStages.mockResolvedValue([playoffStage()]);
  getTournament.mockResolvedValue({ id: 84, name: "Cup" });
  getStagesProgress.mockResolvedValue([{ stage_id: 10, total: 7, completed: 0 }]);
  getTeams.mockResolvedValue({ results: [] });
  getEncounters.mockResolvedValue({ results: ENCOUNTERS, total: ENCOUNTERS.length });

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

/** The round's row, addressed by the accessible name of its date field. */
function row(label: string): HTMLTableRowElement {
  const found = dateLabels()
    .find((element) => element.textContent === `Start time for ${label}`)
    ?.closest("tr");
  if (!(found instanceof HTMLTableRowElement)) throw new Error(`no row for round "${label}"`);
  return found;
}

/** The `sr-only` labels naming each row's date trigger. */
function dateLabels(): HTMLLabelElement[] {
  return [...container.querySelectorAll<HTMLLabelElement>("label")].filter((element) =>
    (element.textContent ?? "").startsWith("Start time for ")
  );
}

/** The clock half of the row's picker — its only text input. */
function timeField(label: string): HTMLInputElement {
  const input = row(label).querySelector("input");
  if (!(input instanceof HTMLInputElement)) throw new Error(`no time field for "${label}"`);
  return input;
}

/** The date half — the popover trigger, which prints the chosen day. */
function dateTrigger(label: string): HTMLButtonElement {
  const button = row(label).querySelector("button");
  if (!(button instanceof HTMLButtonElement)) throw new Error(`no date trigger for "${label}"`);
  return button;
}

/** Today on the viewer's clock — the day an empty picker adopts when only a
 *  time is typed into it. */
function todayAt(time: string): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${time}`;
}

/** The row's Apply button — the picker owns the other buttons in the row. */
function applyButton(label: string): HTMLButtonElement {
  const button = [...row(label).querySelectorAll("button")].find(
    (element) => (element.textContent ?? "").trim() === "Apply"
  );
  if (!button) throw new Error(`no apply button for "${label}"`);
  return button;
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

function roundLabels(): string[] {
  return dateLabels().map((element) =>
    (element.textContent ?? "").replace("Start time for ", "")
  );
}

function dialogButton(text: string): HTMLElement | null {
  const dialog = document.querySelector('[role="alertdialog"]');
  return (
    [...(dialog?.querySelectorAll<HTMLElement>("button") ?? [])].find(
      (element) => (element.textContent ?? "").trim() === text
    ) ?? null
  );
}

/** `[encounterId, scheduled_at]` of every PATCH, in call order. */
function patches(): [number, string | null][] {
  // `vi.fn()` erases the signature; this mock stands in for
  // `adminService.updateEncounter(id, EncounterUpdateInput)`.
  const calls = updateEncounter.mock.calls as [number, EncounterUpdateInput][];
  return calls.map(([id, payload]) => [id, payload.scheduled_at ?? null]);
}

beforeEach(() => {
  vi.clearAllMocks();
  if (root) {
    act(() => root.unmount());
    container.remove();
  }
  updateEncounter.mockResolvedValue(undefined);
});

describe("Stage editor round schedule", () => {
  it("offers one row per round the stage's matches carry, named as the bracket names it", async () => {
    await mount();

    // Round 3 has no matches, so it has no row; round -1 is the lower bracket.
    expect(roundLabels()).toEqual(["UB Round 1", "UB Semifinal", "LB Round 1"]);
    // Four matches in round 1 — the fifth belongs to stage 20.
    expect(row("UB Round 1").textContent).toContain("4");
    // The moved match is called out where the count is.
    expect(row("UB Semifinal").textContent).toContain("1 moved");
    // Reachable: the editor lists it beside the other stage sections.
    expect(
      [...container.querySelectorAll("nav a")].some(
        (anchor) => (anchor.textContent ?? "").trim() === "Round schedule"
      )
    ).toBe(true);
  });

  it("prefills a round with the time its matches already share", async () => {
    await mount();

    expect(timeField("UB Round 1").value).toBe("");
    // The picker shows the instant most of round 2 carries, on the viewer's
    // clock — derived from the same conversion, so the claim holds in any zone.
    const local = utcToZonedInput("2026-05-02T15:00:00.000Z", VIEWER_ZONE);
    expect(timeField("UB Semifinal").value).toBe(local.slice(11));
    expect(dateTrigger("UB Semifinal").textContent).toContain(
      String(Number(local.slice(8, 10)))
    );
  });

  it("writes the chosen time to every match of the round, one request each", async () => {
    await mount();

    // An empty picker takes today's date, so the clock alone names an instant.
    await type(timeField("UB Round 1"), "18:00");
    await click(applyButton("UB Round 1"));

    const expected = zonedInputToUtc(todayAt("18:00"), VIEWER_ZONE);
    expect(patches()).toEqual([
      [1, expected],
      [2, expected],
      [3, expected],
      [4, expected]
    ]);
    // The bracket and the matches views render these times.
    expect(invalidateWorkspace).toHaveBeenCalled();
  });

  it("asks before overwriting a match that was moved on its own", async () => {
    await mount();

    await click(applyButton("UB Semifinal"));

    // Nothing written yet — the question comes first.
    expect(updateEncounter).not.toHaveBeenCalled();
    const dialogs = document.querySelectorAll('[role="alertdialog"]');
    expect(dialogs).toHaveLength(1);
    expect(dialogs[0].textContent).toContain("Overwrite 1 individual time?");
    // The round is named inside the plural, so the question says WHICH round.
    expect(dialogs[0].textContent).toContain(
      "1 match in UB Semifinal was moved on its own"
    );

    await click(dialogButton("Overwrite all"));

    // Both matches of the round, the moved one included.
    expect(patches().map(([id]) => id)).toEqual([5, 6]);
  });

  it("keeps the moved match and still schedules the rest when the question is declined", async () => {
    await mount();

    await click(applyButton("UB Semifinal"));
    await click(dialogButton("Cancel"));

    expect(patches().map(([id]) => id)).toEqual([5]);
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
  });
});
