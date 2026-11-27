// @vitest-environment happy-dom
//
// Account settings render in the root chrome, inside every zone's bundle, and those bundles ship only
// `pickBan.mixBans` and `pickBan.rules.preset` of the pick-ban namespace (`check-zone-boundaries` Z4). So the ban
// default mounts under the real projections, not the test setup's whole-English fallback.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import MixBalancerSection from "@/components/account-settings/MixBalancerSection";
import en from "@/i18n/messages/en.json";
import { pickMessages } from "@/i18n/zones";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

vi.mock("@/services/mix-preferences.service", () => ({
  mixPreferencesKeys: { all: ["mix-preferences"] },
  mixPreferencesService: {
    get: async () => ({
      mix_comfort_tilt: null,
      role_settings: null,
      max_result_variants: null,
      open_slot_settings: null,
      points_per_win: null,
      rating_mode: "points",
      hero_ban_presets: { overwatch: "hero_classic" },
      formation_defaults: {},
      mix_rules: null,
    }),
    update: async (preferences: unknown) => preferences,
  },
}));
vi.mock("@/hooks/useGameScope", async () => {
  const { gameScopeStub } = await import("@/test/game-scope");
  return { useGameScope: () => gameScopeStub({ kind: "game", code: "overwatch", source: "default" }, { axis: "all" }) };
});
vi.mock("@/hooks/useDisciplineMetadata", () => ({ useDisciplineMetadata: () => ({ data: undefined, isError: false }) }));
vi.mock("@/services/pickBan.service", () => ({
  default: {
    getRulesCatalog: async () => ({
      leaves: [],
      constraints: [],
      groups: { hero: [], map: [] },
      presets: [
        {
          id: "hero_classic",
          kind: "hero",
          modes: ["pool"],
          first_ban_rotation: null,
          ruleset: { version: 2, timer_seconds: null, on_timeout: "random_fill", phases: [] },
          mix_eligible: true,
        },
      ],
    }),
  },
}));

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

describe.each(["root", "tools", "web"] as const)("the per-game ban default under the %s bundle", (zone) => {
  it("is labelled, shows the stored preset by name and offers no bans by name", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    await act(async () => {
      createRoot(container).render(
        // A missing message renders its dotted key instead of the copy; the assertions read the copy.
        <NextIntlClientProvider locale="en" messages={pickMessages(en, zone)} onError={() => undefined}>
          <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
            <MixBalancerSection />
          </QueryClientProvider>
        </NextIntlClientProvider>,
      );
    });
    for (let settled = 0; settled < 2; settled += 1) {
      await act(async () => {
        await tick();
      });
    }

    expect(container.querySelector('label[for="mix-ban-default"]')?.textContent).toBe(
      en.accountSettings.mixBalancer.bans.label,
    );
    const select = container.querySelector("#mix-ban-default");
    expect(select?.textContent?.trim()).toBe(en.pickBan.rules.preset.hero_classic);

    await act(async () => {
      select?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
      select?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await tick();
    });
    expect([...document.querySelectorAll('[role="option"]')].map((node) => node.textContent?.trim())).toEqual([
      en.pickBan.mixBans.none,
      en.pickBan.rules.preset.hero_classic,
    ]);
  });
});
