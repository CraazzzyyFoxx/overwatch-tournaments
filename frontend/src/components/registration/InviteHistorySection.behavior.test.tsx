// @vitest-environment happy-dom
//
// The invite ledger, now a right-hand drawer. Two gaps it closes, and both are
// about invisibility:
//
// 1. The team read returns only LIVE pending invites, because occupancy depends on
//    them reserving roster slots. So a DECLINED offer vanished — the captain saw
//    the slot reopen with no idea whether they were refused or the link lapsed.
// 2. The cap counts every invite ever created, so an invite→revoke→invite loop
//    burned the ceiling silently and produced a refusal with no cause on screen.
//
// The closed-costs-nothing promise is asserted too: the trigger sits in a card
// most captains open for other reasons.
//
// Content assertions read `document.body`, not the mount container: the drawer's
// content is portaled out of the tree, the same way `MyTeamPanel.picker.test.tsx`
// reads its dialog.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";

import InviteHistorySection from "./InviteHistorySection";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listInviteHistory = vi.fn();

vi.mock("@/services/registration-team.service", () => ({
  default: { listInviteHistory: (...args: unknown[]) => listInviteHistory(...args) },
}));

const MESSAGES = { en, ru } as const;

const ENTRY = {
  id: 1,
  slot_code: "damage",
  is_substitute: false,
  state: "declined",
  target_battle_tag: "Ana#1111",
  is_link: false,
  invited_at: "2026-08-20T12:00:00Z",
  expires_at: null,
  answered_at: "2026-08-21T09:00:00Z",
  revoked_by_organizer: false,
};

const LEDGER = { items: [{ ...ENTRY }], cap_used: 12, cap_limit: 60, cap_reset_at: null };

async function mount(
  { open = true, locale = "en" as "en" | "ru" } = {},
): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  await act(async () => {
    createRoot(container).render(
      <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]}>
        <QueryClientProvider client={client}>
          <InviteHistorySection
            workspaceId={1}
            teamId={7}
            open={open}
            onOpenChange={() => {}}
          />
        </QueryClientProvider>
      </NextIntlClientProvider>,
    );
  });
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
  return container;
}

/** The drawer's own content, which Radix portals to `document.body`. */
function drawerText(): string {
  return document.body.textContent ?? "";
}

beforeEach(() => {
  listInviteHistory.mockReset().mockResolvedValue({ ...LEDGER });
  document.body.innerHTML = "";
});

describe("invite history drawer", () => {
  it("costs nothing while closed", async () => {
    // The trigger lives in a card captains open to manage a roster, not to read
    // a ledger. A request on every mount would tax everyone for a rare need.
    const container = await mount({ open: false });

    expect(listInviteHistory).not.toHaveBeenCalled();
    // The trigger itself must still be there, or the data is unreachable.
    expect(container.querySelector("button")).not.toBeNull();
    // Radix owns this now: `SheetTrigger` is a dialog trigger, so it reports
    // its own collapsed state rather than this hand-rolling disclosure ARIA.
    expect(container.querySelector("button")?.getAttribute("aria-expanded")).toBe("false");
  });

  it("shows the declined offer that used to vanish", async () => {
    await mount();

    expect(listInviteHistory).toHaveBeenCalledWith(7);
    expect(drawerText()).toContain("Declined");
    expect(drawerText()).toContain("Ana#1111");
    // The slot is a glyph now, so it must still ANNOUNCE the translated slot
    // rather than conveying the role by picture alone.
    const glyph = document.body.querySelector('[role="img"]');
    expect(glyph?.getAttribute("aria-label")).toBe("Damage");
  });

  it("explains the ceiling the refusal talks about", async () => {
    await mount();

    expect(drawerText()).toContain("12 of 60");
  });

  it("says the count has a floor when an organizer moved it", async () => {
    // Without this "12 of 60" reads as the team's whole lifetime, which is exactly
    // the confusion a reset would otherwise create.
    listInviteHistory.mockResolvedValue({ ...LEDGER, cap_reset_at: "2026-08-01T00:00:00Z" });

    await mount();

    expect(drawerText()).toContain("Counted since");
  });

  it("warns before the ceiling instead of after it", async () => {
    listInviteHistory.mockResolvedValue({ ...LEDGER, cap_used: 57 });

    await mount();

    // Names both ways out; a bare number would leave the captain stuck.
    expect(drawerText()).toContain("Revoke an outstanding invite");
    expect(drawerText()).toContain("organizer");
  });

  it("stays quiet about the ceiling when it is far away", async () => {
    await mount();

    expect(drawerText()).not.toContain("Close to the limit");
  });

  it("names an organizer withdrawal as such", async () => {
    // Same `revoked` state, materially different event — and the reason the write
    // path records provenance instead of the reader guessing from who captains now.
    listInviteHistory.mockResolvedValue({
      ...LEDGER,
      items: [{ ...ENTRY, state: "revoked", revoked_by_organizer: true }],
    });

    await mount();

    expect(drawerText()).toContain("Withdrawn by an organizer");
  });

  it("labels a link invite instead of leaving its addressee blank", async () => {
    listInviteHistory.mockResolvedValue({
      ...LEDGER,
      items: [{ ...ENTRY, target_battle_tag: null, is_link: true }],
    });

    await mount();

    expect(drawerText()).toContain("Shareable link");
  });

  it("renders a state it does not know as itself", async () => {
    // A sixth server state must not turn a row into a raw key path. This is the
    // third place in this feature where a typed translator would otherwise render
    // `registrationTeams.history.state.<x>` to a user.
    listInviteHistory.mockResolvedValue({ ...LEDGER, items: [{ ...ENTRY, state: "quarantined" }] });

    await mount();

    expect(drawerText()).toContain("quarantined");
    expect(drawerText()).not.toMatch(/history\.state\./);
  });

  it("says an opened ledger is empty rather than showing a gap", async () => {
    // Distinct from closed: the captain asked, so silence would read as broken.
    listInviteHistory.mockResolvedValue({ ...LEDGER, items: [] });

    await mount();

    expect(drawerText()).toContain("No invites have been issued yet");
  });

  it("renders every key it asks for in Russian too", async () => {
    await mount({ locale: "ru" });

    expect(drawerText()).toContain("Отклонено");
    expect(drawerText()).not.toMatch(/registrationTeams\.|rosterShape\./);
  });
});
