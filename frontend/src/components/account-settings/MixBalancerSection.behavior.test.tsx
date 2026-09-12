// @vitest-environment happy-dom
//
// The panel writes the whole preference row on every save, so the two ways it
// can silently misbehave are both about what lands on the wire:
//
//  1. a knob left where the engine would have put it anyway must travel as
//     `null` — storing an explicit 0.5 or 500 would make "never touched"
//     indistinguishable from "deliberately set to the default", and would put
//     a row on every account that ever opened this tab;
//  2. Save must stay inert until something actually changed, or opening the
//     tab writes a row by itself.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MixBalancerSection from "@/components/account-settings/MixBalancerSection";
import type { MixBalancerPreferences } from "@/services/mix-preferences.service";

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

const UNSET: MixBalancerPreferences = {
  mix_comfort_tilt: null,
  mix_role_weights: null,
  max_result_variants: null,
};

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
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

function saveButton(scope: ParentNode) {
  const button = [...scope.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === "mixBalancer.save",
  );
  if (!button) throw new Error("Expected the Save button");
  return button;
}

function field(scope: ParentNode, id: string) {
  const input = scope.querySelector<HTMLInputElement>(`#${id}`);
  if (!input) throw new Error(`Expected the ${id} field`);
  return input;
}

// React tracks the input's own `value` setter, so write through the prototype
// one (mirrors the mix dialog's test).
const nativeValueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;

async function typeInto(input: HTMLInputElement, value: string) {
  await act(async () => {
    nativeValueSetter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function click(node: Element) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

beforeEach(() => {
  document.body.innerHTML = "";
  getPreferences.mockReset().mockResolvedValue(UNSET);
  updatePreferences.mockReset().mockImplementation((preferences) => Promise.resolve(preferences));
});

describe("MixBalancerSection", () => {
  it("offers no save until a knob moves", async () => {
    const scope = await mount();

    expect(saveButton(scope).hasAttribute("disabled")).toBe(true);

    await typeInto(field(scope, "mix-result-variants"), "200");

    expect(saveButton(scope).hasAttribute("disabled")).toBe(false);
  });

  it("stores only what differs from the engine's own defaults", async () => {
    const scope = await mount();

    await typeInto(field(scope, "mix-role-weight-tank"), "2.5");
    await typeInto(field(scope, "mix-result-variants"), "200");
    await click(saveButton(scope));

    expect(updatePreferences).toHaveBeenCalledWith({
      // Untouched slider: nothing stored, the engine's weighting applies.
      mix_comfort_tilt: null,
      mix_role_weights: { tank: 2.5 },
      max_result_variants: 200,
    });
  });

  it("clears a knob put back to its default instead of pinning it", async () => {
    getPreferences.mockResolvedValue({
      mix_comfort_tilt: null,
      mix_role_weights: { tank: 2.5 },
      max_result_variants: 200,
    });
    const scope = await mount();

    await typeInto(field(scope, "mix-role-weight-tank"), "1");
    await typeInto(field(scope, "mix-result-variants"), "500");
    await click(saveButton(scope));

    expect(updatePreferences).toHaveBeenCalledWith(UNSET);
  });
});
