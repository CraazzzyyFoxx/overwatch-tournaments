// @vitest-environment happy-dom
//
// The two settings sections that carve up the old registration form. The
// message-parity test only proves en.json and ru.json agree with each other; it
// cannot see a key a page ASKS for that neither file defines — next-intl then
// renders the raw key path, which reads as a broken page.
//
// The subscription-rule summary is asserted here because it moved out of the
// questionnaire builder with the rest of the admission rules, and it is the one
// string on these screens that is composed rather than looked up.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, forwardRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import AdmissionSettingsPage from "./admission/page";
import RegistrationSettingsPage from "./registration/page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getRegistrationForm = vi.fn();

vi.mock("@/services/balancer-admin.service", () => ({
  default: {
    getRegistrationForm: (...args: unknown[]) => getRegistrationForm(...args),
    upsertRegistrationForm: vi.fn()
  }
}));

vi.mock("@/services/admin.service", () => ({
  default: {
    getTournament: vi.fn().mockResolvedValue({
      id: 1,
      workspace_id: 3,
      // Team registration, so the team-level admission rules are on screen —
      // they are half the keys this test exists to resolve.
      team_formation: "registration"
    })
  }
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "1" }),
  usePathname: () => "/admin/tournaments/1/settings/admission",
  useSearchParams: () => new URLSearchParams(""),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() })
}));

vi.mock("next/link", () => ({
  default: forwardRef<
    HTMLAnchorElement,
    { href: string; children: React.ReactNode } & React.AnchorHTMLAttributes<HTMLAnchorElement>
  >(function Link({ href, children, ...props }, ref) {
    return (
      <a ref={ref} href={href} {...props}>
        {children}
      </a>
    );
  })
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isLoaded: true, canAccessPermission: () => true })
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

const MESSAGES = { en, ru } as const;

let container: HTMLDivElement;
let root: Root;

async function renderSection(page: () => React.ReactNode, locale: "en" | "ru") {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });

  await act(async () => {
    root.render(
      <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]}>
        <QueryClientProvider client={client}>{page()}</QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  // No early break on "a switch exists": the switches render from defaults
  // before the saved form lands, and the composed rule summary below is the one
  // string that only appears once it has.
  for (let i = 0; i < 8; i += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 10);
      await promise;
    });
  }
}

beforeEach(() => {
  getRegistrationForm.mockReset().mockResolvedValue({
    id: 9,
    tournament_id: 1,
    workspace_id: 3,
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
    hide_registrations: true,
    max_participants: 60,
    max_substitutes: 2,
    form_schema: { schema_version: 1, sections: [] },
    version_id: 1,
    version_number: 1
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("registration settings sections i18n", () => {
  for (const locale of ["en", "ru"] as const) {
    it(`resolves every Registration key in ${locale}`, async () => {
      await renderSection(() => <RegistrationSettingsPage />, locale);

      const text = container.textContent ?? "";
      expect(text).not.toMatch(/registrationFormAdmin\./);
      expect(text).toContain(MESSAGES[locale].registrationFormAdmin.page.display.maxParticipants);
      expect(text).toContain(MESSAGES[locale].registrationFormAdmin.status.autoApproveLabel);
    });

    it(`resolves every Admission key in ${locale}, rule summary included`, async () => {
      await renderSection(() => <AdmissionSettingsPage />, locale);

      const text = container.textContent ?? "";
      expect(text).not.toMatch(/registrationFormAdmin\./);
      expect(text).not.toMatch(/subscriptionRequirement\./);
      // Composed from the workspace rule, not looked up — the string that used
      // to come out Russian in both locales.
      expect(text).toContain(
        locale === "ru" ? "Boosty уровень 2 или Twitch" : "Boosty level 2 or Twitch"
      );
      // Team-formation gated: these rows exist only for registered teams.
      expect(text).toContain(MESSAGES[locale].registrationFormAdmin.page.team.rankSpread);
    });
  }

  it("leaves the team-level rules out of a tournament with no registered teams", async () => {
    // Rank spread and duplicate-identity checks need a roster to run against;
    // a balancer tournament has none until the balancer builds one.
    const admin = await import("@/services/admin.service");
    vi.mocked(admin.default.getTournament).mockResolvedValueOnce({
      id: 1,
      workspace_id: 3,
      team_formation: "balancer"
    } as never);

    await renderSection(() => <AdmissionSettingsPage />, "en");

    const text = container.textContent ?? "";
    expect(text).toContain(en.registrationFormAdmin.page.admission.requireOpenProfile);
    expect(text).not.toContain(en.registrationFormAdmin.page.team.rankSpread);
  });
});
