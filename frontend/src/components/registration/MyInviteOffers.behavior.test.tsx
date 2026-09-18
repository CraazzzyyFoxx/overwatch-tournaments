// @vitest-environment happy-dom
//
// The only surface on which a targeted invite exists. It carries no token, so no
// link and no landing page can reveal it — if this component renders nothing, the
// whole addressed-invite mode is invisible and therefore dead. That is what these
// tests pin, not the markup.
//
// Mounted in both locales for the reason `MyTeamPanel.i18n.test.tsx` documents:
// the parity test proves en.json and ru.json agree with *each other* and cannot
// see a key this component asks for that neither file defines.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import { ApiError } from "@/lib/api-error";
import type { Tournament } from "@/types/tournament.types";

import MyInviteOffers from "./MyInviteOffers";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listMyInvites = vi.fn();
const accept = vi.fn();
const decline = vi.fn();
const notifyError = vi.fn();
const notifySuccess = vi.fn();
let authStatus = "authenticated";
let authUser: unknown = { id: 1 };

// The factory is hoisted above the declarations above it, so it must reference
// them lazily rather than close over their values.
vi.mock("@/lib/notify", () => ({
  notify: {
    success: (...args: unknown[]) => notifySuccess(...args),
    error: (...args: unknown[]) => notifyError(...args),
    apiError: vi.fn()
  }
}));
vi.mock("@/hooks/useAuthProfile", () => ({
  useAuthProfile: () => ({ status: authStatus, user: authUser })
}));
vi.mock("@/services/registration-team.service", () => ({
  default: {
    listMyInvites: (...args: unknown[]) => listMyInvites(...args),
    accept: (...args: unknown[]) => accept(...args),
    decline: (...args: unknown[]) => decline(...args)
  }
}));

const MESSAGES = { en, ru } as const;

const TOURNAMENT = { id: 5, workspace_id: 1, name: "Autumn Cup" } as unknown as Tournament;

const OFFER = {
  invite_id: 42,
  team_id: 7,
  team_name: "Alpha",
  slot_code: "damage",
  is_substitute: false,
  expires_at: null
};

async function mount(locale: "en" | "ru" = "en"): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  await act(async () => {
    createRoot(container).render(
      <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]}>
        <QueryClientProvider client={client}>
          <MyInviteOffers tournament={TOURNAMENT} />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
  return container;
}

beforeEach(() => {
  authStatus = "authenticated";
  authUser = { id: 1 };
  listMyInvites.mockReset().mockResolvedValue({ items: [{ ...OFFER }] });
  accept.mockReset().mockResolvedValue({});
  decline.mockReset().mockResolvedValue(undefined);
  notifyError.mockReset();
  notifySuccess.mockReset();
  document.body.innerHTML = "";
});

describe("my invite offers", () => {
  it("shows an addressed invite that nothing else could reveal", async () => {
    const container = await mount();

    expect(listMyInvites).toHaveBeenCalledWith(5);
    expect(container.textContent).toContain("Alpha");
    // The slot reads through the shared translations, not as a raw wire code.
    expect(container.textContent).toContain("Damage");
  });

  it("accepts with no form, because an existing registration just attaches", async () => {
    // The invitee already registered — the backend reuses that row and ignores any
    // body. Sending a payload here would make them re-answer a form they filled,
    // and the field used to be required-but-ignored, which forced a cast.
    const container = await mount();
    const buttons = [...container.querySelectorAll("button")];

    await act(async () => {
      buttons[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(accept).toHaveBeenCalledWith({ invite_id: 42 });
    expect(accept.mock.calls[0][0]).not.toHaveProperty("registration");
    expect(notifySuccess).toHaveBeenCalled();
  });

  it("declines the same offer by id", async () => {
    const container = await mount();
    const buttons = [...container.querySelectorAll("button")];

    await act(async () => {
      buttons[1].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(decline).toHaveBeenCalledWith({ invite_id: 42 });
  });

  it("surfaces a stale-snapshot refusal in the user's language", async () => {
    // Expected in normal use: another captain can recruit the viewer between this
    // list loading and them pressing Join. Untranslated it would render the
    // server's English msg on a Russian-first surface.
    //
    // A real `ApiError`, not a look-alike literal: the translator narrows on
    // `instanceof`, so a literal takes the generic fallback — and asserting only
    // that SOMETHING was reported would then pass with the English message.
    accept.mockRejectedValue(
      new ApiError(409, [{ code: "player_not_free", msg: "That player already joined a team" }])
    );

    const container = await mount("ru");
    const buttons = [...container.querySelectorAll("button")];

    await act(async () => {
      buttons[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(notifyError).toHaveBeenCalledWith(ru.registrationTeams.errors.player_not_free);
    expect(notifyError).not.toHaveBeenCalledWith("That player already joined a team");
  });

  it("renders nothing at all when there is nothing to answer", async () => {
    // This sits on a page every visitor sees; an empty card there is pure noise.
    listMyInvites.mockResolvedValue({ items: [] });

    const container = await mount();

    expect(container.textContent).toBe("");
  });

  it("renders nothing for a signed-out visitor and asks the server nothing", async () => {
    authStatus = "unauthenticated";
    authUser = null;

    const container = await mount();

    expect(container.textContent).toBe("");
    expect(listMyInvites).not.toHaveBeenCalled();
  });

  it("names a substitute offer differently from a starting one", async () => {
    // Same team, same slot, materially different offer: a bench seat is not the
    // slot the recipient would assume from the starting sentence.
    listMyInvites.mockResolvedValue({
      items: [{ ...OFFER, is_substitute: true, slot_code: "support" }]
    });

    const container = await mount();

    expect(container.textContent).toContain("substitute");
    expect(container.textContent).toContain("Support");
  });

  it("renders every key it asks for in Russian too", async () => {
    const container = await mount("ru");

    expect(container.textContent).toContain("Alpha");
    expect(container.textContent).toContain("Вступить");
    expect(container.textContent).not.toMatch(/registrationTeams\.|rosterShape\./);
  });
});
