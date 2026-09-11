// @vitest-environment happy-dom
//
// `messages.parity.test.ts` proves en.json and ru.json agree with each other, and
// `registration-team-errors.test.ts` proves every backend error code is
// translated. Neither can see a key this component *asks for* that neither file
// defines — next-intl then renders the raw key path, which reads as a broken page.
//
// This mounts the densest team-registration surface in both locales and fails on
// any unresolved lookup. MyTeamPanel is chosen because it consumes the widest slice
// of the namespace: status, inviteState, list, invite, member and disband.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import type { RegistrationTeam } from "@/types/registration-team.types";

import MyTeamPanel from "./MyTeamPanel";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() },
}));
vi.mock("@/services/registration-team.service", () => ({
  default: {
    invite: vi.fn(),
    revokeInvite: vi.fn(),
    kick: vi.fn(),
    leave: vi.fn(),
    transferCaptaincy: vi.fn(),
    disband: vi.fn(),
  },
}));

const MESSAGES = { en, ru } as const;

/** An incomplete team with one open slot, a pending link invite, a substitute and
 *  a non-captain member — so every conditional branch renders at once. */
const TEAM: RegistrationTeam = {
  id: 7,
  tournament_id: 1,
  name: "Alpha",
  image_url: null,
  status: "forming",
  captain_registration_id: 100,
  exported_team_id: null,
  members: [
    {
      registration_id: 100,
      display_name: "Cap",
      battle_tag: "Cap#1111",
      slot_code: "tank",
      is_substitute: false,
      is_captain: true,
      status: "approved",
    },
    {
      registration_id: 101,
      display_name: "Mate",
      battle_tag: "Mate#2222",
      slot_code: "dps",
      is_substitute: false,
      is_captain: false,
      status: "approved",
    },
    {
      registration_id: 102,
      display_name: "Bench",
      battle_tag: "Bench#3333",
      slot_code: "dps",
      is_substitute: true,
      is_captain: false,
      status: "approved",
    },
  ],
  invites: [
    {
      id: 500,
      slot_code: "support",
      is_substitute: false,
      state: "pending",
      target_battle_tag: null,
      is_link: true,
      expires_at: "2026-09-01T10:00:00Z",
      invited_at: "2026-08-20T10:00:00Z",
    },
  ],
  open_slots: { dps: 1, support: 2 },
  shortfall: "1x dps, 2x support",
  is_complete: false,
  substitutes_used: 1,
  max_substitutes: 2,
};

async function renderPanel(locale: "en" | "ru", isCaptain: boolean) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  await act(async () => {
    root.render(
      <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]}>
        <QueryClientProvider client={client}>
          <MyTeamPanel
            workspaceId={1}
            tournamentId={1}
            team={TEAM}
            isCaptain={isCaptain}
            registrationOpen
            checkInAvailable={false}
          />
        </QueryClientProvider>
      </NextIntlClientProvider>,
    );
  });
  return { container, root };
}

describe("MyTeamPanel i18n", () => {
  for (const locale of ["en", "ru"] as const) {
    it(`renders the captain view in ${locale} with no unresolved message keys`, async () => {
      const errors: unknown[][] = [];
      const spy = vi.spyOn(console, "error").mockImplementation((...args) => {
        errors.push(args);
      });

      const { container, root } = await renderPanel(locale, true);
      const text = container.textContent ?? "";

      expect(text).not.toMatch(/registrationTeams\./);
      expect(
        errors.filter((args) => /MISSING_MESSAGE|INSUFFICIENT_PATH|IntlError/.test(String(args[0]))),
      ).toEqual([]);

      // Sanity: the copy is actually localized, not the same string twice.
      expect(text).toContain(locale === "ru" ? "Собирается" : "Forming");
      expect(text).toContain(locale === "ru" ? "Капитан" : "Captain");
      expect(text).toContain(locale === "ru" ? "Запасной" : "Substitute");
      expect(text).toContain(locale === "ru" ? "Распустить команду" : "Disband the team");

      await act(async () => {
        root.unmount();
      });
      container.remove();
      spy.mockRestore();
    });
  }

  it("renders the member view with no unresolved keys and no captain controls", async () => {
    const { container, root } = await renderPanel("ru", false);
    const text = container.textContent ?? "";

    expect(text).not.toMatch(/registrationTeams\./);
    // A non-captain gets exactly one action: leaving.
    expect(text).toContain("Покинуть команду");
    expect(text).not.toContain("Распустить команду");
    expect(text).not.toContain("Пригласить игрока");
    // ...and must not see the roster-editing controls either.
    expect(text).not.toContain("Исключить из команды");

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("renders the shortfall from open_slots with TRANSLATED slot labels", async () => {
    // Two bugs pinned at once. The API ships `shortfall: "1x dps, 2x support"` —
    // raw slot codes in an English shape — which must not reach a Russian
    // sentence. And the labels must come from `rosterShape.slotCodes`, the same
    // set the chips use: an earlier version reached for the hardcoded-English
    // `ROLE_LABELS`, so one card read "1× DPS" beside a "Урон" chip.
    //
    // Read off the dictionary rather than spelled out here, because spelling
    // them out is the very coupling this pins against: the glossary sweep in
    // a26165cc renamed dps/support to Дамаг/Саппорт, and a literal expectation
    // failed for the one reason that is not a bug.
    const { container, root } = await renderPanel("ru", true);
    const text = container.textContent ?? "";
    const slot = ru.rosterShape.slotCodes;

    expect(text).toContain(`1× ${slot.dps}`);
    expect(text).toContain(`2× ${slot.support}`);
    expect(text).not.toContain("1x dps");
    expect(text).not.toContain("1× DPS");

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });
});
