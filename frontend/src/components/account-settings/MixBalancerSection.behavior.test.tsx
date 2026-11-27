// @vitest-environment happy-dom
//
// The panel has no Save button: every knob writes itself once it stops moving,
// which puts three things on the line that are cheap to get wrong —
//
//  1. a knob left where the engine would have put it anyway must travel as
//     `null`; storing an explicit 0.5 or 100 would make "never touched"
//     indistinguishable from "deliberately set to the default", and would put
//     a row on every account that ever opened this tab;
//  2. a burst of edits (or a slider dragged across the track) must collapse
//     into ONE write, not one per keystroke;
//  3. opening the tab, or nudging a knob back to what is already stored, must
//     write nothing at all.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MixBalancerSection from "@/components/account-settings/MixBalancerSection";
import type { MixBalancerPreferencesRead } from "@/services/mix-preferences.service";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const getPreferences = vi.fn();
const updatePreferences = vi.fn();

vi.mock("@/services/mix-preferences.service", () => ({
  mixPreferencesKeys: { all: ["mix-preferences"] },
  mixPreferencesService: {
    get: () => getPreferences(),
    update: (preferences: unknown) => updatePreferences(preferences),
  },
}));
/** The game tab the panel is on; a case switches it to prove each game keeps its own ban default. */
const tab = vi.hoisted(() => ({ game: "overwatch" }));
vi.mock("@/hooks/useGameScope", async () => {
  const { gameScopeStub } = await import("@/test/game-scope");
  return { useGameScope: () => gameScopeStub({ kind: "game", code: tab.game, source: "default" }, { axis: "all" }) };
});
// The server's catalog: each game's presets, with the `mix_eligible` flag it computes.
vi.mock("@/services/pickBan.service", () => {
  const preset = (id: string, kind: "hero" | "map", mix_eligible: boolean) => ({
    id,
    kind,
    modes: ["pool"],
    first_ban_rotation: null,
    ruleset: { version: 2, timer_seconds: null, on_timeout: "random_fill", phases: [] },
    mix_eligible,
  });
  const presets: Record<string, unknown[]> = {
    overwatch: [
      preset("hero_classic", "hero", true),
      preset("hero_targeted", "hero", false),
      preset("hero_anti_one_trick", "hero", true),
      preset("map_bracket", "map", false),
    ],
    deadlock: [preset("deadlock_hero_bans", "hero", true), preset("map_bracket", "map", false)],
  };
  return {
    default: {
      getRulesCatalog: async (discipline: string) => ({
        leaves: [],
        constraints: [],
        groups: { hero: [], map: [] },
        presets: presets[discipline] ?? [],
      }),
    },
  };
});
vi.mock("@/hooks/useDisciplineMetadata", () => ({
  useDisciplineMetadata: () => ({ data: {
    discipline: { code: "overwatch" }, workspace_id: null,
    dimensions: [{ id: 1, code: "player_role", name: "Role", active: true, rated: true, selection_mode: "single", sort_order: 0 }],
    roles: ["tank", "damage", "support"].map((code, id) => ({ id, code, name: code, dimension: "player_role", active: true, selectable: true, parent_id: null, workspace_id: null, sort_order: id, attrs: {} }))
  }, isError: false })
}));

// Labels come through as their message keys; this panel's contract is the
// payload, not the copy.
vi.mock("next-intl", () => ({ useTranslations: () => Object.assign((key: string) => key, { has: () => false }) }));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() },
}));

const UNSET: MixBalancerPreferencesRead = {
  mix_comfort_tilt: null,
  role_settings: null,
  max_result_variants: null,
  open_slot_settings: null,
  points_per_win: null,
  rating_mode: "points",
  hero_ban_presets: {},
  formation_defaults: {},
  mix_rules: null,
};

/** Longer than the panel's own debounce, so a settled write has fired. */
const AFTER_AUTOSAVE_MS = 1000;

function tick(ms = 0) {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, ms);
  return promise;
}

const mounted: Root[] = [];

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  mounted.push(root);
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <MixBalancerSection />
      </QueryClientProvider>,
    );
  });
  await act(async () => {
    await tick();
  });
  // The ban select's catalog read starts once the stored row has rendered the panel.
  await act(async () => {
    await tick();
  });
  return container;
}

function unmountAll() {
  for (const root of mounted.splice(0)) act(() => root.unmount());
}

function field(scope: ParentNode, id: string) {
  const input = scope.querySelector<HTMLInputElement>(`#${id}`);
  if (!input) throw new Error(`Expected the ${id} field`);
  return input;
}

// React tracks the input's own `value` setter, so write through the prototype
// one (mirrors the other mix tests).
const nativeValueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;

async function typeInto(input: HTMLInputElement, value: string) {
  await act(async () => {
    nativeValueSetter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function settle() {
  await act(async () => {
    await tick(AFTER_AUTOSAVE_MS);
  });
}

async function click(element: Element | null | undefined) {
  if (!element) throw new Error("Expected an element to click");
  await act(async () => {
    element.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

async function choose(scope: ParentNode, id: string, label: string) {
  await click(field(scope, id));
  await click([...document.querySelectorAll('[role="option"]')].find((node) => node.textContent?.trim() === label));
}

/** A fake of the stored row: what a save writes is what the next read answers. */
function storeAcrossMounts() {
  let stored: MixBalancerPreferencesRead = UNSET;
  getPreferences.mockImplementation(() => Promise.resolve(stored));
  updatePreferences.mockImplementation((preferences: MixBalancerPreferencesRead) => {
    stored = preferences;
    return Promise.resolve(preferences);
  });
}

beforeEach(() => {
  unmountAll();
  document.body.innerHTML = "";
  tab.game = "overwatch";
  getPreferences.mockReset().mockResolvedValue(UNSET);
  updatePreferences.mockReset().mockImplementation((preferences) =>
    Promise.resolve(preferences),
  );
});

describe("MixBalancerSection", () => {
  it("writes nothing while nothing has changed", async () => {
    await mount();
    await settle();

    expect(updatePreferences).not.toHaveBeenCalled();
  });

  it("stores a burst of edits as one row, with the untouched knobs as null", async () => {
    const scope = await mount();

    await typeInto(field(scope, "mix-role-weight-tank"), "2.5");
    await typeInto(field(scope, "mix-role-weight-flex"), "0.5");
    await typeInto(field(scope, "mix-result-variants"), "40");
    await typeInto(field(scope, "mix-points-per-win"), "50");
    await settle();

    expect(updatePreferences).toHaveBeenCalledTimes(1);
    expect(updatePreferences).toHaveBeenCalledWith(expect.objectContaining({
      // Untouched knobs use the engine defaults.
      mix_comfort_tilt: null,
      role_settings: { tank: { mix_weight: 2.5 } },
      max_result_variants: 40,
      open_slot_settings: { mix_weight: 0.5 },
      points_per_win: 50,
      rating_mode: "points",
    }));
  });

  it("clears a knob put back to its default instead of pinning it", async () => {
    getPreferences.mockResolvedValue({
      ...UNSET,
      role_settings: { tank: { mix_weight: 2.5 } },
      max_result_variants: 40,
      points_per_win: 50,
    });
    const scope = await mount();

    await typeInto(field(scope, "mix-role-weight-tank"), "1");
    // Past the ceiling is the ceiling, and the ceiling is the default.
    await typeInto(field(scope, "mix-result-variants"), "500");
    await typeInto(field(scope, "mix-points-per-win"), "0");
    await settle();

    expect(updatePreferences).toHaveBeenCalledWith(expect.objectContaining({
      mix_comfort_tilt: null,
      role_settings: null,
      max_result_variants: null,
      open_slot_settings: null,
      points_per_win: null,
      rating_mode: "points",
    }));
  });

  it("locks the points field (without clearing it) while the ranker owns the ranks", async () => {
    getPreferences.mockResolvedValue({ ...UNSET, points_per_win: 50, rating_mode: "ranker" });
    const scope = await mount();

    const points = field(scope, "mix-points-per-win");
    expect(points.disabled).toBe(true);
    expect(points.value).toBe("50");

    await settle();
    expect(updatePreferences).not.toHaveBeenCalled();
  });

  it("offers only the ban presets the server lets a mix of this game play", async () => {
    const scope = await mount();

    await click(field(scope, "mix-ban-default"));

    // Labels read as their keys: the copy is mocked out.
    expect([...document.querySelectorAll('[role="option"]')].map((node) => node.textContent?.trim())).toEqual([
      "none",
      "hero_classic",
      "hero_anti_one_trick",
    ]);
  });

  it("keeps each game's ban default across save and reload", async () => {
    storeAcrossMounts();

    await choose(await mount(), "mix-ban-default", "hero_classic");
    await settle();
    unmountAll();
    tab.game = "deadlock";
    await choose(await mount(), "mix-ban-default", "deadlock_hero_bans");
    await settle();
    unmountAll();

    tab.game = "overwatch";
    expect(field(await mount(), "mix-ban-default").textContent?.trim()).toBe("hero_classic");
    unmountAll();
    tab.game = "deadlock";
    expect(field(await mount(), "mix-ban-default").textContent?.trim()).toBe("deadlock_hero_bans");
  });

  it("keeps each game's formation and pick clock across save and reload", async () => {
    storeAcrossMounts();

    const overwatch = await mount();
    await choose(overwatch, "mix-formation-overwatch-formation", "formationDraft");
    await typeInto(field(overwatch, "mix-formation-overwatch-pick-seconds"), "45");
    await settle();
    // Leaving for another settings tab unmounts the section without ever blurring the clock: the typed value must
    // already be in the autosaved draft.
    unmountAll();

    tab.game = "deadlock";
    const deadlock = await mount();
    expect(field(deadlock, "mix-formation-deadlock-formation").textContent?.trim()).toBe("formationBalance");
    expect(deadlock.querySelector("#mix-formation-deadlock-pick-seconds")).toBeNull();
    unmountAll();

    tab.game = "overwatch";
    const reloaded = await mount();
    expect(field(reloaded, "mix-formation-overwatch-formation").textContent?.trim()).toBe("formationDraft");
    expect(field(reloaded, "mix-formation-overwatch-pick-seconds").value).toBe("45");
  });
});
