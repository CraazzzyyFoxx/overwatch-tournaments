// @vitest-environment happy-dom
//
// The landing page for a shared invite link. Before this route existed the invite
// dialog copied a bare token and there was nowhere to paste it: `InviteAcceptWizard`
// was defined and rendered by nothing. So these tests pin the reachability of the
// whole invitee flow, not just its copy.
//
// Mounted in both locales for the same reason `MyTeamPanel.i18n.test.tsx` is: the
// parity test proves en.json and ru.json agree with *each other*, and cannot see a
// key this page asks for that neither file defines.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";

import InviteLandingPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const previewInvite = vi.fn();
const getForm = vi.fn();
const push = vi.fn();
const openAuthModal = vi.fn();
let authStatus = "unauthenticated";
let authUser: unknown = null;

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/hooks/useAuthProfile", () => ({
  useAuthProfile: () => ({ status: authStatus, user: authUser }),
}));
vi.mock("@/stores/auth-modal.store", () => ({
  useAuthModalStore: (selector: (s: unknown) => unknown) => selector({ open: openAuthModal }),
}));
vi.mock("@/services/registration-team.service", () => ({
  default: { previewInvite: (...args: unknown[]) => previewInvite(...args) },
}));
vi.mock("@/services/registration.service", () => ({
  default: { getForm: (...args: unknown[]) => getForm(...args) },
}));
// The wizard's own contract is covered elsewhere; here it stands in as a marker
// that the page reached the point of offering the form at all.
vi.mock("@/components/registration/InviteAcceptWizard", () => ({
  default: ({ teamName, slotCode }: { teamName: string; slotCode: string }) => (
    <div data-testid="wizard">{`wizard:${teamName}:${slotCode}`}</div>
  ),
}));

const MESSAGES = { en, ru } as const;

const TOKEN = "PcWqruHUOoQe4AmdJagQPh_fpjqq2e9qJ61GJgRSIDI";

const PREVIEW = {
  tournament_id: 5,
  tournament_name: "Autumn Cup",
  workspace_id: 1,
  team_id: 7,
  team_name: "Alpha",
  slot_code: "damage",
  is_substitute: false,
  state: "pending",
  expires_at: null,
  is_redeemable: true,
};

async function mount(locale: "en" | "ru" = "en"): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  await act(async () => {
    createRoot(container).render(
      <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]}>
        <QueryClientProvider client={client}>
          <InviteLandingPage />
        </QueryClientProvider>
      </NextIntlClientProvider>,
    );
  });
  // Three flushes, one per link in a chain that is sequential BY DESIGN: the
  // fragment is only readable after hydration commits, the preview needs the
  // token, and the registration form needs the tournament id the preview
  // returns. Nothing here can be parallelised, so nothing here can be skipped.
  for (let turn = 0; turn < 3; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
  return container;
}

beforeEach(() => {
  window.location.hash = `#${TOKEN}`;
  authStatus = "unauthenticated";
  authUser = null;
  previewInvite.mockReset().mockResolvedValue({ ...PREVIEW });
  getForm.mockReset().mockResolvedValue({ id: 1, tournament_id: 5, is_open: true });
  push.mockReset();
  openAuthModal.mockReset();
  document.body.innerHTML = "";
});

describe("invite landing page", () => {
  it("resolves the token from the fragment and shows the offer", async () => {
    const container = await mount();

    // The token must reach the service — otherwise the link is decorative.
    expect(previewInvite).toHaveBeenCalledWith(TOKEN);
    expect(container.textContent).toContain("Alpha");
    expect(container.textContent).toContain("Autumn Cup");
    // The slot renders through the shared translations, not as a raw wire code.
    expect(container.textContent).toContain("Damage");
  });

  it("shows the offer BEFORE asking an anonymous visitor to sign in", async () => {
    // The ordering is the feature: a link invite reaches someone with no account,
    // and a sign-in wall with no context reads as phishing.
    const container = await mount();

    expect(container.textContent).toContain("Alpha");
    expect(container.querySelector("button")).not.toBeNull();
    expect(container.querySelector('[data-testid="wizard"]')).toBeNull();

    await act(async () => {
      container.querySelector("button")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(openAuthModal).toHaveBeenCalled();
    // No `nextPath`: a redirect would drop the fragment, and the fragment is the token.
    expect(openAuthModal).toHaveBeenCalledWith();
  });

  it("offers the accept form once the visitor is signed in", async () => {
    authStatus = "authenticated";
    authUser = { id: 1 };

    const container = await mount();

    expect(container.textContent).toContain("wizard:Alpha:damage");
    expect(getForm).toHaveBeenCalledWith(5);
  });

  it("explains an expired link instead of offering a doomed form", async () => {
    // `state` stays `pending` — that IS the row's state — while redeemability is
    // false. A page keyed on state alone would render the accept form and let the
    // guarded UPDATE reject it after the visitor filled it in.
    authStatus = "authenticated";
    authUser = { id: 1 };
    previewInvite.mockResolvedValue({
      ...PREVIEW,
      expires_at: "2020-01-01T00:00:00Z",
      is_redeemable: false,
    });

    const container = await mount();

    expect(container.textContent).toContain("expired");
    expect(container.querySelector('[data-testid="wizard"]')).toBeNull();
    // The offer still renders: a dead link should say what it *was* for.
    expect(container.textContent).toContain("Alpha");
  });

  it("names the captain's withdrawal rather than blaming the link", async () => {
    previewInvite.mockResolvedValue({ ...PREVIEW, state: "revoked", is_redeemable: false });

    const container = await mount();

    expect(container.textContent).toContain("withdrawn by the captain");
  });

  it("falls back to a generic line for an invite state it does not know", async () => {
    // A server that grows a fifth state must not turn this page into a raw
    // `landing.dead.<state>` key path.
    previewInvite.mockResolvedValue({ ...PREVIEW, state: "quarantined", is_redeemable: false });

    const container = await mount();

    expect(container.textContent).toContain("no longer available");
    expect(container.textContent).not.toContain("landing.dead");
  });

  it("tells a visitor with no link that they need one, and asks the server nothing", async () => {
    window.location.hash = "";

    const container = await mount();

    expect(container.textContent).toContain("invite link");
    expect(previewInvite).not.toHaveBeenCalled();
  });

  it("renders every key it asks for in Russian too", async () => {
    authStatus = "authenticated";
    authUser = { id: 1 };

    const container = await mount("ru");

    expect(container.textContent).toContain("Приглашение");
    expect(container.textContent).not.toMatch(/registrationTeams\./);
  });

  it("renders the dead-link vocabulary in Russian", async () => {
    previewInvite.mockResolvedValue({ ...PREVIEW, state: "accepted", is_redeemable: false });

    const container = await mount("ru");

    expect(container.textContent).toContain("уже использовано");
    expect(container.textContent).not.toMatch(/landing\.dead/);
  });
});
