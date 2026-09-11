// @vitest-environment happy-dom
//
// Registered teams (organizer side). What is pinned here:
//  1. the shortfall is rendered from `open_slots` through the shared role
//     labels, never from the server's English `shortfall` string;
//  2. it is a T2 browser: rows in a table, chips that write the URL, one kebab
//     per row, and the detail in the inspector at `?id=`;
//  3. only a roster the server would materialize can be selected for export,
//     and the teams are named back before it runs;
//  4. a rejection cannot be sent without a reason its captain can read, and the
//     consequence is opt-in;
//  5. "Place player" takes a PLAYER (a free agent of this tournament) and sends
//     their registration id — the field used to ask for that id directly.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { ApiError } from "@/lib/api-error";
import type { RegistrationTeam } from "@/types/registration-team.types";
import { RegistrationTeamsBrowser } from "./RegistrationTeamsBrowser";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TOURNAMENT_ID = 80;
const WORKSPACE_ID = 3;
const PATH = `/admin/tournaments/${TOURNAMENT_ID}/registration/teams`;

let currentSearch = "";
let rerender: (() => void) | null = null;

const replace = vi.fn((url: string) => {
  const query = url.includes("?") ? url.slice(url.indexOf("?")) : "";
  currentSearch = query;
  window.history.replaceState(null, "", `${PATH}${query}`);
  rerender?.();
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => PATH,
  useSearchParams: () => new URLSearchParams(currentSearch)
}));

const listAdmin = vi.fn();
const reject = vi.fn();
const exportRegistered = vi.fn();
const revokeInviteAdmin = vi.fn();
const resetInviteCap = vi.fn();
const listInviteHistoryAdmin = vi.fn();
const listFreeAgents = vi.fn();
const placeMemberAdmin = vi.fn();
const notifySuccess = vi.fn();
const notifyInfo = vi.fn();
const notifyError = vi.fn();

vi.mock("@/services/registration-team.service", () => ({
  default: {
    listAdmin: (...args: unknown[]) => listAdmin(...args),
    reject: (...args: unknown[]) => reject(...args),
    exportRegistered: (...args: unknown[]) => exportRegistered(...args),
    revokeInviteAdmin: (...args: unknown[]) => revokeInviteAdmin(...args),
    resetInviteCap: (...args: unknown[]) => resetInviteCap(...args),
    listInviteHistoryAdmin: (...args: unknown[]) => listInviteHistoryAdmin(...args),
    listFreeAgents: (...args: unknown[]) => listFreeAgents(...args),
    placeMemberAdmin: (...args: unknown[]) => placeMemberAdmin(...args),
    unlockRoster: vi.fn(),
    renameAdmin: vi.fn(),
    setAdmission: vi.fn(),
    setNotes: vi.fn()
  }
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ canAccessPermission: () => true, isLoaded: true, isSuperuser: true })
}));
vi.mock("@/lib/notify", () => ({
  notify: {
    success: (...args: unknown[]) => notifySuccess(...args),
    info: (...args: unknown[]) => notifyInfo(...args),
    error: (...args: unknown[]) => notifyError(...args)
  }
}));

function team(overrides: Partial<RegistrationTeam> = {}): RegistrationTeam {
  return {
    id: 1,
    tournament_id: TOURNAMENT_ID,
    name: "Team Alpha",
    image_url: null,
    status: "forming",
    captain_registration_id: 11,
    exported_team_id: null,
    members: [
      {
        registration_id: 11,
        display_name: "Nyx",
        battle_tag: "Nyx#2100",
        slot_code: "tank",
        is_substitute: false,
        is_captain: true,
        status: "approved"
      }
    ],
    invites: [
      {
        id: 5,
        slot_code: "dps",
        is_substitute: false,
        state: "pending",
        target_battle_tag: null,
        is_link: true,
        expires_at: "2027-09-01T12:00:00Z",
        invited_at: "2026-08-20T12:00:00Z"
      }
    ],
    open_slots: { dps: 1, support: 2 },
    shortfall: "1x dps, 2x support",
    is_complete: false,
    substitutes_used: 0,
    max_substitutes: 1,
    ...overrides
  };
}

const COMPLETE_TEAM = team({
  id: 2,
  name: "Team Beta",
  status: "complete",
  invites: [],
  open_slots: {},
  shortfall: "",
  is_complete: true
});

// Roots are tracked so afterEach can tear them down (see TournamentLogsTab's
// behavior suite: React 19 otherwise dereferences `window` after teardown).
const mounted: { root: Root; container: HTMLElement }[] = [];

function tick(ms = 0) {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function settle(ms = 0) {
  for (let turn = 0; turn < 5; turn += 1) {
    await act(async () => {
      await tick(ms);
    });
  }
}

function Harness() {
  const [, force] = useState(0);
  // Published from an effect, not during render: writing a module-scope binding
  // while rendering is a side effect the react-compiler rules reject.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <RegistrationTeamsBrowser tournamentId={TOURNAMENT_ID} workspaceId={WORKSPACE_ID} />;
}

async function mount(search = "") {
  currentSearch = search;
  window.history.replaceState(null, "", `${PATH}${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          <Harness />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
  return container;
}

async function click(node: Element | null | undefined) {
  expect(node).toBeTruthy();
  await act(async () => {
    // Radix opens a dropdown on `pointerdown`; everything else answers `click`.
    node?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle();
}

function row(scope: ParentNode, name: string): HTMLElement | undefined {
  return [...scope.querySelectorAll<HTMLElement>("tbody tr")].find((node) =>
    node.textContent?.includes(name)
  );
}

/** The row's `⋯` menu, opened. Its items are portaled outside the table. */
async function rowMenu(scope: ParentNode, name: string): Promise<HTMLElement[]> {
  await click(scope.querySelector(`button[aria-label='Actions for ${name}']`));
  return [...document.body.querySelectorAll<HTMLElement>("[role='menuitem']")];
}

function menuItem(items: HTMLElement[], text: string): HTMLElement | undefined {
  return items.find((item) => (item.textContent ?? "").includes(text));
}

function buttonWithText(scope: ParentNode, text: string): HTMLButtonElement | undefined {
  return [...scope.querySelectorAll("button")].find((node) => node.textContent?.includes(text)) as
    HTMLButtonElement | undefined;
}

function commandItem(label: string): Element | undefined {
  return [...document.querySelectorAll('[cmdk-item=""]')].find((item) =>
    item.textContent?.trim().startsWith(label)
  );
}

/** Types into a controlled field the way React hears it. */
async function type(field: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto =
    field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  await act(async () => {
    setter?.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle();
}

/** Radix portals the confirmation outside the render container. */
function confirmDialog(): HTMLElement | null {
  return document.body.querySelector("[role='alertdialog']");
}

function formDialog(): HTMLElement | null {
  return document.body.querySelector("[role='dialog']");
}

async function submit(dialog: HTMLElement) {
  const form = dialog.querySelector("form");
  expect(form).toBeTruthy();
  await act(async () => {
    form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await settle();
}

beforeEach(() => {
  currentSearch = "";
  rerender = null;
  replace.mockClear();
  listAdmin.mockReset().mockResolvedValue({ items: [team(), COMPLETE_TEAM], total: 2 });
  reject.mockReset().mockResolvedValue(team({ status: "rejected" }));
  exportRegistered.mockReset().mockResolvedValue({
    removed_teams: 0,
    imported_teams: 1,
    created_players: 5,
    skipped: []
  });
  revokeInviteAdmin.mockReset().mockResolvedValue(undefined);
  resetInviteCap.mockReset().mockResolvedValue(undefined);
  placeMemberAdmin.mockReset().mockResolvedValue(team());
  // Only read once the place dialog opens.
  listFreeAgents.mockReset().mockResolvedValue({
    items: [
      { registration_id: 41, battle_tag: "Ana#1111", roles: ["support"] },
      { registration_id: 42, battle_tag: "Rein#2222", roles: ["tank"] }
    ],
    total: 2
  });
  // The ledger is collapsed at mount, so this resolves only once a block is opened.
  listInviteHistoryAdmin
    .mockReset()
    .mockResolvedValue({ items: [], cap_used: 0, cap_limit: 60, cap_reset_at: null });
  notifySuccess.mockReset();
  notifyInfo.mockReset();
  notifyError.mockReset();
  // The inspector is a side panel above `lg` and a sheet below it.
  window.matchMedia = ((query: string) => ({
    matches: true,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false
  })) as unknown as typeof window.matchMedia;
});

afterEach(async () => {
  await act(async () => {
    for (const { root, container } of mounted.splice(0)) {
      root.unmount();
      container.remove();
    }
  });
  document.body.innerHTML = "";
  document.body.style.pointerEvents = "";
});

describe("RegistrationTeamsBrowser", () => {
  it("summarizes every team the organizer has to judge", async () => {
    const scope = await mount();

    // The reason the screen exists: which roster is still short, and by what.
    // Rendered from `open_slots` through the shared role labels, NOT from the
    // server's English `shortfall` string.
    expect(scope.textContent).toContain("Still needed: 1× Damage, 2× Support");
    expect(scope.textContent).not.toContain("1x dps");
    expect(scope.textContent).toContain("Roster complete");
    expect(row(scope, "Team Alpha")?.textContent).toContain("Nyx");
    expect(row(scope, "Team Alpha")?.textContent).toContain("Starters: 1 of 4");
    // One read serves every filter below, so terminal teams are already here.
    expect(listAdmin).toHaveBeenCalledTimes(1);
    expect(listAdmin).toHaveBeenCalledWith(TOURNAMENT_ID, { includeTerminal: true });
  });

  it("narrows the list from a chip that lives in the URL", async () => {
    const rejected = team({ id: 3, name: "Team Gamma", status: "rejected" });
    listAdmin.mockReset().mockResolvedValue({
      items: [team(), COMPLETE_TEAM, rejected],
      total: 3
    });
    const scope = await mount();

    await click(scope.querySelector("button[aria-label='Add filter']"));
    await click(commandItem("State"));
    await click(commandItem("Rejected and disbanded"));

    // A filter that lives in component state cannot be linked; this one is the URL.
    expect(new URL(replace.mock.calls.at(-1)![0], "http://x").searchParams.get("state")).toBe(
      "terminal"
    );
    expect(row(scope, "Team Gamma")).toBeTruthy();
    expect(row(scope, "Team Alpha")).toBeUndefined();
    expect(listAdmin).toHaveBeenCalledTimes(1);
  });

  it("narrows by name without a second request", async () => {
    listAdmin.mockReset().mockResolvedValue({
      items: [team(), COMPLETE_TEAM, team({ id: 3, name: "Team Gamma", status: "rejected" })],
      total: 3
    });
    const scope = await mount();

    await type(scope.querySelector("input[name='admin-table-search']") as HTMLInputElement, "beta");
    // The table's search is debounced.
    await settle(120);

    expect(row(scope, "Team Beta")).toBeTruthy();
    expect(row(scope, "Team Gamma")).toBeUndefined();
    expect(listAdmin).toHaveBeenCalledTimes(1);
  });

  it("warns the organizer about players the export cannot place", async () => {
    // The silent failure this closes: the export materializes registered TEAMS, and
    // on a team-registration tournament neither the balancer nor the draft runs, so
    // a player nobody invited never becomes a tournament.player and nothing said so.
    listAdmin
      .mockReset()
      .mockResolvedValue({ items: [team(), COMPLETE_TEAM], total: 2, unassigned_players: 3 });

    const scope = await mount();

    expect(scope.textContent).toContain("3 players are on no team");
    // Actionable, not just a number: the two ways out are named.
    expect(scope.textContent).toContain("invite them to a team or withdraw them");
  });

  it("stays quiet when every registered player is on a team", async () => {
    // A warning that fires at zero is a warning organizers learn to ignore.
    listAdmin
      .mockReset()
      .mockResolvedValue({ items: [COMPLETE_TEAM], total: 1, unassigned_players: 0 });

    const scope = await mount();

    expect(scope.textContent).not.toContain("on no team");
  });

  it("exports only the teams the organizer picked, named back before it runs", async () => {
    // The old button materialized every complete team at once, which is
    // irreversible for teams the organizer had not looked at yet.
    const scope = await mount();

    await click(scope.querySelector(`[aria-label='Select row ${COMPLETE_TEAM.id}']`));
    await click(buttonWithText(scope, "Add selected teams"));

    const dialog = confirmDialog();
    expect(dialog?.textContent).toContain("Team Beta");
    expect(dialog?.textContent).not.toContain("Team Alpha");
    expect(exportRegistered).not.toHaveBeenCalled();

    await click(buttonWithText(dialog!, "Add selected teams"));

    expect(exportRegistered).toHaveBeenCalledWith(TOURNAMENT_ID, [COMPLETE_TEAM.id]);
  });

  it("cannot select a roster the server would skip", async () => {
    listAdmin.mockReset().mockResolvedValue({ items: [team()], total: 1 });

    const scope = await mount();

    // No checkbox at all rather than a disabled one: the row is not a candidate.
    expect(scope.querySelector("[aria-label='Select row 1']")).toBeNull();
    expect(buttonWithText(scope, "Add selected teams")).toBeUndefined();
  });

  it("keeps the export result and every skipped team on screen after the toast", async () => {
    exportRegistered.mockResolvedValue({
      removed_teams: 0,
      imported_teams: 1,
      created_players: 5,
      skipped: [{ team_id: 9, name: "Team Gamma", code: "team_incomplete" }]
    });

    const scope = await mount();
    await click(scope.querySelector(`[aria-label='Select row ${COMPLETE_TEAM.id}']`));
    await click(buttonWithText(scope, "Add selected teams"));
    await click(buttonWithText(confirmDialog()!, "Add selected teams"));

    // A toast expires; an organizer must still be able to see which team did not
    // go, and why.
    expect(scope.textContent).toContain("Teams added: 1");
    expect(scope.textContent).toContain("Team Gamma: roster incomplete");
  });

  it("refuses to reject a team without a reason its captain can read", async () => {
    const scope = await mount();

    await click(menuItem(await rowMenu(scope, "Team Alpha"), "Reject team"));
    const dialog = confirmDialog()!;
    await click(buttonWithText(dialog, "Reject, keep registrations"));

    expect(reject).not.toHaveBeenCalled();
    expect(dialog.textContent).toContain("Give a reason");

    await type(dialog.querySelector("textarea") as HTMLTextAreaElement, "  Duplicate roster  ");
    await click(buttonWithText(dialog, "Reject, keep registrations"));

    // Non-destructive by default: the players keep the registration they can
    // still use on another team.
    expect(reject).toHaveBeenCalledWith(TOURNAMENT_ID, 1, {
      withdrawMembers: false,
      reason: "Duplicate roster"
    });
    expect(notifySuccess).toHaveBeenCalledWith("Team rejected.");
  });

  it("withdraws the players only when that consequence is chosen", async () => {
    const scope = await mount();

    await click(menuItem(await rowMenu(scope, "Team Alpha"), "Reject team"));
    const dialog = confirmDialog()!;
    await type(dialog.querySelector("textarea") as HTMLTextAreaElement, "Roster never filled");
    await click(dialog.querySelectorAll("[role='radio']")[1]);
    await click(buttonWithText(dialog, "Reject and withdraw registrations"));

    expect(reject).toHaveBeenCalledWith(TOURNAMENT_ID, 1, {
      withdrawMembers: true,
      reason: "Roster never filled"
    });
  });

  it("keeps a refused action on screen, in the organizer's language", async () => {
    // A toast expires before an organizer has read it, and the server's English
    // `msg` must never reach them.
    reject.mockRejectedValue(
      new ApiError(409, [{ msg: "Team was already exported", code: "team_already_exported" }])
    );

    const scope = await mount();
    await click(menuItem(await rowMenu(scope, "Team Alpha"), "Reject team"));
    const dialog = confirmDialog()!;
    await type(dialog.querySelector("textarea") as HTMLTextAreaElement, "Duplicate roster");
    await click(buttonWithText(dialog, "Reject, keep registrations"));

    expect(document.body.textContent).toContain(
      "This team has already been added to the tournament and can no longer be changed."
    );
    expect(document.body.textContent).not.toContain("Team was already exported");
  });

  it("shows the organizer the invites the public roster hides", async () => {
    const scope = await mount();
    await click(row(scope, "Team Alpha"));

    // Row detail is the inspector, and it is addressable.
    expect(new URL(replace.mock.calls.at(-1)![0], "http://x").searchParams.get("id")).toBe("1");

    const inspector = document.body.querySelector("aside[aria-label='Row inspector']");
    expect(inspector?.textContent).toContain("Pending");
    expect(inspector?.textContent).toContain("Shareable link");

    // The id in the path is the TOURNAMENT, not just the invite: an invite id is
    // global while the organizer's permission is not.
    await click(document.body.querySelector("button[aria-label='Withdraw invite']"));

    expect(revokeInviteAdmin).toHaveBeenCalledWith(TOURNAMENT_ID, 5);
  });

  it("resets a team's invite count only after a confirmation", async () => {
    // The cap counts every invite ever issued, so a team that cycled offers is
    // stuck; until this existed the refusal named an intervention no endpoint
    // provided. It is still someone else's roster, hence the confirm.
    const scope = await mount();

    await click(menuItem(await rowMenu(scope, "Team Alpha"), "Reset invite count"));
    expect(resetInviteCap).not.toHaveBeenCalled();

    await click(buttonWithText(confirmDialog()!, "Reset invite count"));

    expect(resetInviteCap).toHaveBeenCalledWith(TOURNAMENT_ID, 1);
  });

  it("does not read a team's ledger until it is opened", async () => {
    // One request per team on every render would tax the organizer for a history
    // they rarely open.
    await mount("?id=1");

    expect(listInviteHistoryAdmin).not.toHaveBeenCalled();

    await click(buttonWithText(document.body, "Invite history"));

    expect(listInviteHistoryAdmin).toHaveBeenCalledWith(TOURNAMENT_ID, 1);
  });

  it("places a player picked by name, not a registration id typed from memory", async () => {
    const scope = await mount();

    await click(menuItem(await rowMenu(scope, "Team Alpha"), "Place player"));
    const dialog = formDialog()!;
    // The candidates are this tournament's free agents — a player already on a
    // team is not offered, so the call cannot be refused for that.
    expect(listFreeAgents).toHaveBeenCalledWith(TOURNAMENT_ID);

    await click(dialog.querySelector("button[role='combobox']"));
    await click(commandItem("Rein#2222"));
    await submit(dialog);

    expect(placeMemberAdmin).toHaveBeenCalledWith(TOURNAMENT_ID, 1, 42, {
      slot_code: "tank",
      is_substitute: false
    });
  });
});
