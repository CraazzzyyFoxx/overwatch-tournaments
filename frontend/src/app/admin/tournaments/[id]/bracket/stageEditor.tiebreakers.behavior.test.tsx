// @vitest-environment happy-dom
//
// One claim: a tiebreak metric can be turned OFF, not only moved.
//
// The section used to render `tiebreak_order` as a fixed list of every metric
// the catalogue knows, with arrows and nothing else — so "we do not use
// Buchholz here" was unsayable, and an organizer's only lever was to sink the
// metric to the bottom where it still decided the odd pair. Absence from
// `tiebreak_order` IS the disabled state the engine reads, so the switch writes
// exactly that: the metric leaves the saved list.
//
// Pinned through the REAL save mutation (`adminService.updateStage`), because
// the claim is about the payload, not about a checkbox changing colour. Also
// pinned: the two steps the engine owns rather than the editor — `points` is
// forced first and cannot be switched off, `manual_override` is forced last and
// is neither movable nor removable.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Stage } from "@/types/tournament.types";

import BracketTabPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getStages = vi.fn();
const getTournament = vi.fn();
const getStagesProgress = vi.fn();
const updateStage = vi.fn();
const getTeams = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getStages: (...args: unknown[]) => getStages(...args),
    getTournament: (...args: unknown[]) => getTournament(...args),
    getStagesProgress: (...args: unknown[]) => getStagesProgress(...args),
    updateStage: (...args: unknown[]) => updateStage(...args),
    applyStageBestOf: vi.fn()
  }
}));

vi.mock("@/services/team.service", () => ({
  default: { getAll: (...args: unknown[]) => getTeams(...args) }
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isSuperuser: true })
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/tournaments/84/bracket",
  useParams: () => ({ id: "84" }),
  useSearchParams: () => new URLSearchParams("stage=10&section=tiebreakers")
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: unknown }) => (
    <a href={href} {...rest}>
      {children as never}
    </a>
  )
}));

vi.mock("@/lib/tournament-workspace-query-keys", () => ({
  invalidateTournamentWorkspace: vi.fn()
}));

// Radix's Checkbox measures its hidden form input, and the Select reaches for
// pointer-capture APIs happy-dom does not implement.
for (const [name, value] of Object.entries({
  hasPointerCapture: () => false,
  setPointerCapture: () => undefined,
  releasePointerCapture: () => undefined,
  scrollIntoView: () => undefined
})) {
  if (!(name in Element.prototype)) {
    Object.defineProperty(Element.prototype, name, { value, writable: true });
  }
}
if (!("ResizeObserver" in globalThis)) {
  Object.defineProperty(globalThis, "ResizeObserver", {
    writable: true,
    value: class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  });
}

/** A round robin with no saved order, so the editor shows the RR defaults. */
function roundRobinStage(): Stage {
  return {
    id: 10,
    tournament_id: 84,
    name: "Groups",
    description: null,
    stage_type: "round_robin",
    max_rounds: 5,
    advance_count: 2,
    split_lower_bracket: false,
    order: 0,
    is_active: true,
    is_completed: false,
    settings_json: {},
    challonge_id: null,
    challonge_slug: null,
    items: []
  } as unknown as Stage;
}

/** What `defaultTiebreakOrder("round_robin")` puts in the editor on mount. */
const RR_DEFAULT = [
  "points",
  "head_to_head",
  "median_buchholz",
  "match_wins",
  "score_differential",
  "buchholz",
  "manual_override"
];

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
  getStages.mockResolvedValue([roundRobinStage()]);
  getTournament.mockResolvedValue({ id: 84, name: "Cup" });
  getStagesProgress.mockResolvedValue([]);
  getTeams.mockResolvedValue({ results: [] });

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

async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    (element as HTMLElement).click();
  });
  await settle(4);
}

/** The on/off control of one metric, on or off the ordered list. */
function toggle(label: string): HTMLElement {
  const element = document.querySelector<HTMLElement>(
    `[role="checkbox"][aria-label="Use ${label}"]`
  );
  if (!element) throw new Error(`no on/off control for "${label}"`);
  return element;
}

function moveButtons(label: string): HTMLElement[] {
  return [
    ...document.querySelectorAll<HTMLElement>(
      `[aria-label="Move ${label} up"], [aria-label="Move ${label} down"]`
    )
  ];
}

async function save() {
  const button = [...document.querySelectorAll<HTMLElement>("button")].find(
    (element) => (element.textContent ?? "").trim() === "Save changes"
  );
  if (!button) throw new Error("no save control");
  await click(button);
}

function savedOrder(): string[] {
  const [, payload] = updateStage.mock.calls[0] as [
    number,
    { settings_json: { tiebreak_order: string[] } }
  ];
  return payload.settings_json.tiebreak_order;
}

beforeEach(() => {
  vi.clearAllMocks();
  if (root) {
    act(() => root.unmount());
    container.remove();
  }
  updateStage.mockResolvedValue(roundRobinStage());
});

describe("Stage editor tiebreakers, per-metric on/off", () => {
  it("saves the full default order while nothing is switched off", async () => {
    await mount();

    // A no-op section still has to produce the order the engine will use, or
    // "disabled" below would be indistinguishable from "never rendered".
    await click(moveButtons("Match Wins")[0]);
    await save();

    expect(updateStage).toHaveBeenCalledTimes(1);
    expect(savedOrder()).toEqual([
      "points",
      "head_to_head",
      "match_wins",
      "median_buchholz",
      "score_differential",
      "buchholz",
      "manual_override"
    ]);
  });

  it("drops a switched-off metric from the saved order", async () => {
    await mount();

    await click(toggle("Buchholz"));
    await click(toggle("Match Wins"));
    await save();

    expect(updateStage).toHaveBeenCalledTimes(1);
    expect(savedOrder()).toEqual([
      "points",
      "head_to_head",
      "median_buchholz",
      "score_differential",
      "manual_override"
    ]);
    // Absence is the whole mechanism: no "enabled: false" flag rides along.
    expect(savedOrder()).not.toContain("buchholz");
    expect(savedOrder()).not.toContain("match_wins");
  });

  it("keeps a switched-off metric reachable and restores it on the way back", async () => {
    await mount();

    await click(toggle("Median Buchholz"));
    // Still on screen — off the ordered list, but offered again.
    expect(toggle("Median Buchholz").getAttribute("aria-checked")).toBe("false");

    await click(toggle("Median Buchholz"));
    await save();

    // Re-enabled metrics land last, where the arrows can lift them again.
    expect(savedOrder()).toEqual([
      "points",
      "head_to_head",
      "match_wins",
      "score_differential",
      "buchholz",
      "median_buchholz",
      "manual_override"
    ]);
    expect([...savedOrder()].sort()).toEqual([...RR_DEFAULT].sort());
  });

  it("refuses to switch off points: it is the ranking metric, not a tiebreaker", async () => {
    await mount();

    expect(toggle("Points").hasAttribute("disabled")).toBe(true);
    await click(toggle("Points"));

    expect(toggle("Points").getAttribute("aria-checked")).toBe("true");
    // Nothing changed, so there is nothing to save.
    await click(moveButtons("Match Wins")[0]);
    await save();
    expect(savedOrder()[0]).toBe("points");
  });

  it("shows manual override as a fixed system step, neither movable nor removable", async () => {
    await mount();

    expect(moveButtons("Manual Override")).toEqual([]);
    expect(toggle("Manual Override").hasAttribute("disabled")).toBe(true);
    // Every other step keeps both arrows.
    expect(moveButtons("Buchholz")).toHaveLength(2);

    await click(toggle("Buchholz"));
    await save();
    expect(savedOrder().at(-1)).toBe("manual_override");
  });
});
