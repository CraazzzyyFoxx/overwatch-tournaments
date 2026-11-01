// @vitest-environment happy-dom
//
// Inviting onto the BENCH of a team whose starting roster is already full.
//
// `open_slots` is the starter shortfall, so a complete roster reports none — but
// the bench is a separate allowance and is exactly the case where a substitute is
// wanted. The dialog offered its slot radios from `open_slots` alone, so it opened
// empty, the submit fell through a `no slot` guard, and a tournament configured
// with substitute places could never fill one.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { canonicalDisplay } from "@/lib/player";
import type { RegistrationTeam } from "@/types/registration-team.types";

import MyTeamPanel from "./MyTeamPanel";

vi.mock("@/services/discipline.service", async () => (await import("@/test/discipline-metadata")).disciplineServiceMock);

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

const member = (registration_id: number, slot_code: string, is_captain = false) => ({
  registration_id,
  display_name: `P${registration_id}`,
  primary_handle: `P${registration_id}#1000`,
  display: canonicalDisplay(`P${registration_id}`),
  slot_code,
  is_substitute: false,
  is_captain,
  status: "approved"
});

/** Every starter slot taken — `open_slots` empty — with two bench places free. */
const FULL_TEAM: RegistrationTeam = {
  id: 7,
  tournament_id: 1,
  name: "Alpha",
  image_url: null,
  status: "complete",
  captain_registration_id: 100,
  exported_team_id: null,
  members: [member(100, "tank", true), member(101, "damage"), member(102, "support")],
  invites: [],
  open_slots: {},
  shortfall: "",
  is_complete: true,
  substitutes_used: 0,
  max_substitutes: 2
} as unknown as RegistrationTeam;

async function render(team: RegistrationTeam): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    createRoot(container).render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <MyTeamPanel
            discipline="overwatch"
            workspaceId={1}
            tournamentId={1}
            team={team}
            isCaptain
            registrationOpen
            checkInAvailable={false}
          />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
  return container;
}

function findButton(text: string): HTMLButtonElement {
  const match = [...document.querySelectorAll("button")].find((button) =>
    (button.textContent ?? "").includes(text)
  );
  if (!match) throw new Error(`no button matching ${text}`);
  return match as HTMLButtonElement;
}

/** Lets a settled read reach the view: react-query notifies its observers on a zero timeout, so wait one out in act. */
async function settle(): Promise<void> {
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
}

async function click(element: HTMLElement): Promise<void> {
  await act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle();
}

beforeEach(() => {
  invite.mockReset().mockResolvedValue({ id: 5, token: null });
  listFreeAgents.mockReset().mockResolvedValue({ items: [], total: 0 });
  listInviteHistory
    .mockReset()
    .mockResolvedValue({ items: [], cap_used: 0, cap_limit: 60, cap_reset_at: null });
  document.body.innerHTML = "";
});

describe("bench invites on a full starting roster", () => {
  it("offers the roster's slots so a substitute can be invited", async () => {
    await render(FULL_TEAM);
    await click(findButton(en.registrationTeams.invite.action));

    // Radix radios are `<button role="radio" value>` inside the radiogroup the slot label names.
    const group = [...document.querySelectorAll('[role="radiogroup"]')].find(
      (el) => document.getElementById(el.getAttribute("aria-labelledby") ?? "")?.textContent === en.registrationTeams.invite.slotLabel
    );
    const slots = [...(group?.querySelectorAll<HTMLButtonElement>('[role="radio"]') ?? [])];
    expect(slots.map((radio) => radio.value)).toEqual(["tank", "damage", "support"]);

    await click(findButton(en.registrationTeams.invite.submit));

    expect(invite).toHaveBeenCalledTimes(1);
    const [teamId, payload] = invite.mock.calls[0] as [number, Record<string, unknown>];
    expect(teamId).toBe(7);
    expect(payload).toMatchObject({ is_substitute: true, slot_code: "tank" });
  });

  it("hides the invite action when the bench is already spoken for", async () => {
    // Pending substitute offers reserve their place server-side (`can_offer`),
    // so a button that only leads to `bench_full` is a dead end.
    await render({
      ...FULL_TEAM,
      max_substitutes: 1,
      invites: [
        {
          id: 9,
          team_id: 7,
          slot_code: "damage",
          is_substitute: true,
          state: "pending"
        }
      ]
    } as unknown as RegistrationTeam);

    expect(() => findButton(en.registrationTeams.invite.action)).toThrow();
  });
});
