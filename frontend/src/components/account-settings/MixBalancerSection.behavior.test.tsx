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
import { createRoot } from "react-dom/client";
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

// Labels come through as their message keys; this panel's contract is the
// payload, not the copy.
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() },
}));

const UNSET: MixBalancerPreferencesRead = {
  mix_comfort_tilt: null,
  mix_role_weights: null,
  max_result_variants: null,
  role_mask: null,
  points_per_win: null,
  roster_shape: {
    slots: { tank: 1, damage: 2, support: 2 },
    team_size: 5,
    flex_slots: 0,
    has_role_slots: true,
    draft_rounds: 5,
    source: "default",
  },
};

/** Longer than the panel's own debounce, so a settled write has fired. */
const AFTER_AUTOSAVE_MS = 1000;

function tick(ms = 0) {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, ms);
  return promise;
}

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    createRoot(container).render(
      <QueryClientProvider client={client}>
        <MixBalancerSection />
      </QueryClientProvider>,
    );
  });
  await act(async () => {
    await tick();
  });
  return container;
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

beforeEach(() => {
  document.body.innerHTML = "";
  getPreferences.mockReset().mockResolvedValue(UNSET);
  updatePreferences.mockReset().mockImplementation((preferences) =>
    Promise.resolve({ ...preferences, roster_shape: UNSET.roster_shape }),
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
    await typeInto(field(scope, "mix-result-variants"), "40");
    await typeInto(field(scope, "mix-points-per-win"), "50");
    await settle();

    expect(updatePreferences).toHaveBeenCalledTimes(1);
    expect(updatePreferences).toHaveBeenCalledWith({
      // Untouched slider and shape: nothing stored, the defaults apply.
      mix_comfort_tilt: null,
      mix_role_weights: { tank: 2.5 },
      max_result_variants: 40,
      role_mask: null,
      points_per_win: 50,
    });
  });

  it("clears a knob put back to its default instead of pinning it", async () => {
    getPreferences.mockResolvedValue({
      ...UNSET,
      mix_role_weights: { tank: 2.5 },
      max_result_variants: 40,
      points_per_win: 50,
    });
    const scope = await mount();

    await typeInto(field(scope, "mix-role-weight-tank"), "1");
    // Past the ceiling is the ceiling, and the ceiling is the default.
    await typeInto(field(scope, "mix-result-variants"), "500");
    await typeInto(field(scope, "mix-points-per-win"), "0");
    await settle();

    expect(updatePreferences).toHaveBeenCalledWith({
      mix_comfort_tilt: null,
      mix_role_weights: null,
      max_result_variants: null,
      role_mask: null,
      points_per_win: null,
    });
  });
});
