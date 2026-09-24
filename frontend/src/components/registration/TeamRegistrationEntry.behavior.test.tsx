// @vitest-environment happy-dom
//
// Founding a team on a roster made only of `flex` slots — the shape a battle
// royale squad uses (`{flex: 3}`). Two claims, both about what the captain can
// actually reach:
//
// 1. The entry exists at all. The slot list was built by filtering `ROLES`, so a
//    roster with no role slot produced an empty list and the whole "Register a
//    team" affordance silently disappeared: nobody could found a squad.
// 2. A flex slot fixes no role. The captain's slot drives the role step, which
//    is right for `tank`/`damage`/`support` and wrong for `flex` — locking the
//    matrix to a role named "flex" leaves the step with no row at all, so there
//    is nothing to answer and nothing to submit.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { RosterSlotMap } from "@/lib/roster/shape";
import type { RegistrationForm } from "@/types/registration.types";
import type { Tournament } from "@/types/tournament.types";

import TeamRegistrationEntry from "./TeamRegistrationEntry";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getMyRegistration = vi.fn();
const getForm = vi.fn();

vi.mock("@/hooks/useAuthProfile", () => ({
  useAuthProfile: () => ({
    status: "authenticated",
    user: { id: 7, username: "captain", social_accounts: [] },
    error: null,
    refetch: () => {}
  })
}));
vi.mock("@/services/registration.service", () => ({
  default: {
    getMyRegistration: (...args: unknown[]) => getMyRegistration(...args),
    getForm: (...args: unknown[]) => getForm(...args),
    getMySubscriptionStatus: async () => ({ required: false, verdicts: {} })
  }
}));
vi.mock("@/services/registration-team.service", () => ({
  default: { create: vi.fn(), uploadImage: vi.fn() }
}));
vi.mock("@/services/me.service", () => ({
  default: { getSocialAccounts: async () => ({ id: 7, social_accounts: [] }) }
}));
vi.mock("@/services/hero.service", () => ({ default: { getAll: async () => ({ results: [] }) } }));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), apiError: vi.fn() }
}));
vi.mock("@/stores/account-settings-modal.store", () => ({
  useAccountSettingsModalStore: (select: (state: { open: () => void }) => unknown) =>
    select({ open: () => {} })
}));

/** One step asking only for roles: the matrix is the surface the captain's slot
 *  is supposed to drive, so it is the one this file needs on screen. Each role
 *  offers a specialization, which is what gives every matrix row an accessible
 *  name to count. */
const SUBROLE_CATALOG = {
  tank: [{ slug: "main-tank", label: "Main tank" }],
  damage: [{ slug: "hitscan", label: "Hitscan" }],
  support: [{ slug: "main-heal", label: "Main heal" }]
};

const FORM = {
  id: 1,
  tournament_id: 84,
  workspace_id: 3,
  is_open: true,
  version_id: 42,
  version_number: 1,
  subrole_catalog: SUBROLE_CATALOG,
  form_schema: {
    schema_version: 1,
    sections: [
      {
        key: "roles",
        title: "Roles",
        fields: [
          { key: "roles", kind: "builtin", label: "Roles", required: false, visibility: "public", params: {} }
        ]
      }
    ]
  }
} as unknown as RegistrationForm;

function tournament(slots: RosterSlotMap): Tournament {
  const now = Date.now();
  return {
    id: 84,
    workspace_id: 3,
    name: "Widow's Deadly Kiss",
    slug: "widows-deadly-kiss",
    team_formation: "registration",
    status: "registration",
    allow_late_registration: false,
    phase_schedule: [
      {
        status: "registration",
        starts_at: new Date(now - 86_400_000).toISOString(),
        ends_at: new Date(now + 86_400_000).toISOString()
      }
    ],
    roster_slots_json: slots,
    roster_shape: null
  } as unknown as Tournament;
}

let container: HTMLDivElement;
let root: Root;

async function settle() {
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
}

async function mount(slots: RosterSlotMap) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <TeamRegistrationEntry tournament={tournament(slots)} />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
}

/** The "Register a team" button, or `null` when the entry rendered nothing. */
function entryButton(): HTMLButtonElement | null {
  return (
    [...container.querySelectorAll("button")].find((button) =>
      (button.textContent ?? "").includes(en.registrationTeams.create.action)
    ) ?? null
  );
}

async function openWizard() {
  const trigger = entryButton();
  if (!trigger) throw new Error("the register-a-team entry is not on screen");
  await act(async () => {
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle();
}

/** The slot codes the wizard offers, read off the radio group it renders. */
function offeredSlots(): string[] {
  return [...document.querySelectorAll<HTMLInputElement>('input[name="regteam-slot"]')].map(
    (input) => input.value
  );
}

/**
 * The roles the matrix asks about, in order. Each row names its specialization
 * control "{role} specialization", which is the one accessible name a row
 * carries in BOTH modes — the priority control is hidden whenever the step is
 * locked to a single role.
 */
function roleRows(): string[] {
  return [...document.querySelectorAll("[aria-label]")]
    .map((node) => node.getAttribute("aria-label") ?? "")
    .filter((label) => label.endsWith(" specialization"))
    .map((label) => label.replace(" specialization", ""));
}

beforeEach(() => {
  document.body.innerHTML = "";
  getMyRegistration.mockReset().mockResolvedValue(null);
  getForm.mockReset().mockResolvedValue(FORM);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

describe("founding a team on an all-flex roster", () => {
  it("offers the entry and the flex slot", async () => {
    await mount({ flex: 3 });

    expect(entryButton()).not.toBeNull();

    await openWizard();
    expect(offeredSlots()).toEqual(["flex"]);
  });

  it("does not pin the captain to a role", async () => {
    await mount({ flex: 3 });
    await openWizard();

    // A flex slot says "any role", so the matrix must still ask about all of
    // them. Locking it to the literal code "flex" filters every row away.
    expect(roleRows()).toEqual([
      en.rosterShape.slotCodes.tank,
      en.rosterShape.slotCodes.damage,
      en.rosterShape.slotCodes.support
    ]);
  });
});

describe("founding a team on a role roster", () => {
  it("offers each role slot with its multiplicity and pins the chosen one", async () => {
    await mount({ tank: 1, damage: 2, support: 2 });
    await openWizard();

    expect(offeredSlots()).toEqual(["tank", "damage", "support"]);
    // The first slot is preselected, and a role slot DOES fix the role step.
    expect(roleRows()).toEqual([en.rosterShape.slotCodes.tank]);
  });
});
