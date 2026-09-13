// @vitest-environment happy-dom
//
// The message-parity test only proves en.json and ru.json agree with each
// other. It cannot see a key the page *asks* for and neither file defines —
// next-intl then renders the raw key path, which reads as a broken page. This
// mounts the whole builder in both locales and fails on any unresolved lookup.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import RegistrationFormBuilder from "./RegistrationFormBuilder";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@/services/balancer-admin.service", () => ({
  default: {
    getRegistrationForm: vi.fn().mockResolvedValue({
      id: 1,
      workspace_id: 1,
      is_open: true,
      auto_approve: false,
      require_open_profile: true,
      open_profile_scope: "all",
      require_subscription: true,
      subscription_requirement_json: {
        mode: "any",
        requirements: [
          { provider: "boosty", min_tier_rank: 2 },
          { provider: "twitch", min_tier_rank: 1 }
        ]
      },
      show_ranks: false,
      built_in_fields: {},
      custom_fields: [
        { key: "vk", label: "VK", type: "text", required: false, order: 0, options: null }
      ]
    }),
    upsertRegistrationForm: vi.fn()
  }
}));
vi.mock("@/services/admin.service", () => ({
  default: {
    getPlayerSubRoles: vi
      .fn()
      .mockResolvedValue([{ id: 1, role: "tank", slug: "main_tank", label: "Main Tank" }])
  }
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number }) => unknown) =>
    selector({ currentWorkspaceId: 1 })
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

const MESSAGES = { en, ru } as const;

async function renderPage(locale: "en" | "ru") {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  await act(async () => {
    root.render(
      <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]}>
        <QueryClientProvider client={client}>
          <RegistrationFormBuilder tournamentId={1} />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  for (let i = 0; i < 30; i += 1) {
    if (container.querySelector('button[role="switch"]')) break;
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
  }
  return { container, root };
}

describe("admin registration form i18n", () => {
  for (const locale of ["en", "ru"] as const) {
    it(`renders every section in ${locale} with no unresolved message keys`, async () => {
      const errors: unknown[][] = [];
      const spy = vi.spyOn(console, "error").mockImplementation((...args) => {
        errors.push(args);
      });

      const { container, root } = await renderPage(locale);
      // Every section is on the page at once — no in-page tabs to open.
      expect(container.querySelectorAll('[role="tab"]')).toHaveLength(0);

      const text = container.textContent ?? "";
      expect(text).not.toMatch(/registrationFormAdmin\./);
      expect(text).not.toMatch(/subscriptionRequirement\./);
      expect(
        errors.filter((args) => /MISSING_MESSAGE|INSUFFICIENT_PATH|IntlError/.test(String(args[0])))
      ).toEqual([]);

      // Sanity: the localized copy actually differs per locale. The subscription
      // rule summary moved with the admission rules to `settings/admission`,
      // which has its own i18n test.
      expect(text).toContain(locale === "ru" ? "Саброли" : "Subroles");

      await act(async () => {
        root.unmount();
      });
      container.remove();
      spy.mockRestore();
    });
  }
});
