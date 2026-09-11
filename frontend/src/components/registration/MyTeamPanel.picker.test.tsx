// @vitest-environment happy-dom
//
// The captain's half of targeted invites: picking a free agent instead of minting
// a shareable link. Three failure modes are worth pinning and none are visual.
//
// 1. The mode. "Create a link" and "Invite a registered player" are separate
//    choices, so a submit in link mode must never carry an addressee and a
//    submit in targeted mode must never fall back to a link.
// 2. The payload. `target_registration_id` must be ABSENT (not null) for a link
//    invite, because presence is what selects the addressing mode server-side.
// 3. The dialog. A targeted invite returns no token, so a dialog that waits for
//    one shows an empty link box forever.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { ApiError } from "@/lib/api-error";
import type { RegistrationTeam } from "@/types/registration-team.types";

import MyTeamPanel from "./MyTeamPanel";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const invite = vi.fn();
const listFreeAgents = vi.fn();
const listInviteHistory = vi.fn();

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));
vi.mock("@/services/registration-team.service", () => ({
  default: {
    invite: (...args: unknown[]) => invite(...args),
    listFreeAgents: (...args: unknown[]) => listFreeAgents(...args),
    listInviteHistory: (...args: unknown[]) => listInviteHistory(...args),
    revokeInvite: vi.fn(),
    kick: vi.fn(),
    leave: vi.fn(),
    transferCaptaincy: vi.fn(),
    disband: vi.fn(),
    setImage: vi.fn(),
    clearImage: vi.fn()
  }
}));

/** One open `dps` slot so the invite dialog has something to offer. */
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
      display_name: "Nyx",
      battle_tag: "Nyx#2100",
      slot_code: "tank",
      is_substitute: false,
      is_captain: true,
      status: "approved"
    }
  ],
  invites: [],
  open_slots: { dps: 1 },
  shortfall: "1x dps",
  substitutes_used: 0,
  max_substitutes: 2
} as unknown as RegistrationTeam;

const AGENTS = [
  { registration_id: 900, battle_tag: "Ana#1111", roles: ["support"] },
  { registration_id: 901, battle_tag: "Zen#2222", roles: ["dps", "tank"] }
];

async function openDialog(): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  await act(async () => {
    createRoot(container).render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <MyTeamPanel
            workspaceId={1}
            tournamentId={1}
            team={TEAM}
            isCaptain
            registrationOpen
            checkInAvailable={false}
          />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });

  const trigger = [...container.querySelectorAll("button")].find((button) =>
    (button.textContent ?? "").includes(en.registrationTeams.invite.action)
  );
  if (!trigger) throw new Error("invite trigger not rendered");

  await act(async () => {
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
  return container;
}

function findButton(text: string): HTMLButtonElement {
  const match = [...document.querySelectorAll("button")].find((button) =>
    (button.textContent ?? "").includes(text)
  );
  if (!match) throw new Error(`no button matching ${text}`);
  return match as HTMLButtonElement;
}

/** Free-agent rows are a native radio group (`<label><input type="radio">…`),
 *  not buttons, so selecting one activates the input directly rather than
 *  dispatching a click on a `<button>` that no longer exists. */
function selectAgent(text: string): void {
  const label = [...document.querySelectorAll("label")].find((el) =>
    (el.textContent ?? "").includes(text)
  );
  if (!label) throw new Error(`no label matching ${text}`);
  const input = label.querySelector("input");
  if (!input) throw new Error(`label matching ${text} has no input`);
  (input as HTMLInputElement).click();
}

/** The two invite modes are radios like the free-agent rows, so the same
 *  label-then-input activation works for both. */
async function chooseTargetedMode(): Promise<void> {
  await act(async () => {
    selectAgent(en.registrationTeams.invite.modeAccount);
  });
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
}

beforeEach(() => {
  invite.mockReset().mockResolvedValue({ id: 5, token: null });
  listFreeAgents.mockReset().mockResolvedValue({ items: AGENTS, total: AGENTS.length });
  listInviteHistory
    .mockReset()
    .mockResolvedValue({ items: [], cap_used: 60, cap_limit: 60, cap_reset_at: null });
  document.body.innerHTML = "";
});

describe("captain's free-agent picker", () => {
  it("fetches candidates only once the targeted mode is chosen", async () => {
    // A list nobody asked for is a request nobody asked for: link invites never
    // need it, and the dialog opens on the link mode.
    await openDialog();
    expect(listFreeAgents).not.toHaveBeenCalled();

    await chooseTargetedMode();

    expect(listFreeAgents).toHaveBeenCalledWith(1);
  });

  it("offers each candidate with their roles, translated", async () => {
    await openDialog();
    await chooseTargetedMode();
    const text = document.body.textContent ?? "";

    expect(text).toContain("Ana#1111");
    expect(text).toContain("Zen#2222");
    // Roles are the reason the picker is not a bare name list: the captain is
    // filling one slot and must spot a tank without opening profiles.
    expect(text).toContain("Support");
    expect(text).toContain("Tank");
    expect(text).not.toContain("dps");
  });

  it("sends target_registration_id once a candidate is chosen", async () => {
    await openDialog();
    await chooseTargetedMode();

    await act(async () => {
      selectAgent("Ana#1111");
    });
    await act(async () => {
      findButton(en.registrationTeams.invite.submit).dispatchEvent(
        new MouseEvent("click", { bubbles: true })
      );
    });

    expect(invite).toHaveBeenCalledTimes(1);
    expect(invite.mock.calls[0][1]).toMatchObject({ target_registration_id: 900 });
  });

  it("omits the field entirely for a link invite", async () => {
    // Presence selects the mode server-side, so an explicit `null` would be a
    // different request than "no target" — and would resolve nothing.
    await openDialog();

    expect(
      document.querySelector<HTMLInputElement>('input[name="invite-target-agent"]')
    ).toBeNull();

    await act(async () => {
      findButton(en.registrationTeams.invite.submit).dispatchEvent(
        new MouseEvent("click", { bubbles: true })
      );
    });

    expect(invite.mock.calls[0][1]).not.toHaveProperty("target_registration_id");
  });

  it("does not leave an empty link box after a targeted invite", async () => {
    // The link branch renders whatever `token` came back. A targeted invite
    // returns none, so a dialog that stayed open would show an empty box where
    // the copyable link goes.
    await openDialog();
    await chooseTargetedMode();

    await act(async () => {
      selectAgent("Zen#2222");
    });
    await act(async () => {
      findButton(en.registrationTeams.invite.submit).dispatchEvent(
        new MouseEvent("click", { bubbles: true })
      );
    });
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });

    expect(document.body.textContent).not.toContain(en.registrationTeams.invite.tokenTitle);
    expect(document.querySelector("code")).toBeNull();
  });

  it("tells an empty roster of candidates apart from a filtered-out one", async () => {
    // Different situations, different recourses: nobody to recruit versus a search
    // that matched nothing. One message for both would send a captain looking for
    // players who are not there.
    listFreeAgents.mockResolvedValue({ items: [], total: 0 });

    await openDialog();
    await chooseTargetedMode();

    expect(document.body.textContent).toContain(en.registrationTeams.picker.empty);
    expect(document.body.textContent).not.toContain(en.registrationTeams.picker.noMatch);
  });

  it("opens the invite history when the cap refuses an invite", async () => {
    // The whole point of the ledger: the cap counts every invite ever created, so
    // a refusal at the ceiling used to be a dead end with its cause nowhere on
    // screen. The error itself is the trigger — cheaper than counting on every
    // render, and it fires exactly when the number changes a decision.
    // A real instance, not a look-alike literal: the code reader narrows on
    // `instanceof ApiError`, so an object literal silently takes the generic
    // fallback and this test would pass while the feature did nothing.
    invite.mockRejectedValue(
      new ApiError(409, [{ code: "invite_cap_reached", msg: "too many invites" }])
    );

    await openDialog();
    expect(listInviteHistory).not.toHaveBeenCalled();

    await act(async () => {
      findButton(en.registrationTeams.invite.submit).dispatchEvent(
        new MouseEvent("click", { bubbles: true })
      );
    });
    // The chain is longer than one turn: reject -> onError -> setState ->
    // re-render -> the section's query becomes enabled -> fetch.
    for (let turn = 0; turn < 3; turn += 1) {
      await act(async () => {
        const { promise, resolve } = Promise.withResolvers<void>();
        setTimeout(resolve, 0);
        await promise;
      });
    }

    expect(listInviteHistory).toHaveBeenCalledWith(7);
  });

  it("leaves the history closed for any other failure", async () => {
    // A slot collision is not a ceiling problem; opening a ledger would be noise
    // and would tax a read nobody needed.
    invite.mockRejectedValue(new ApiError(409, [{ code: "slot_taken", msg: "slot taken" }]));

    await openDialog();
    await act(async () => {
      findButton(en.registrationTeams.invite.submit).dispatchEvent(
        new MouseEvent("click", { bubbles: true })
      );
    });

    expect(listInviteHistory).not.toHaveBeenCalled();
  });
});
