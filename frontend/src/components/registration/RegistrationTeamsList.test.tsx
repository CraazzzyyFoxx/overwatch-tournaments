// @vitest-environment happy-dom
//
// The viewer's own team is already shown in full detail directly above this
// list (`MyTeamPanel`, via `MyTeamSection`). Rendering it a second time here as
// a summary card of the same roster and shortfall is the exact duplication a
// captain complained about — this pins that it stays gone, not just how it
// currently looks.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { RegistrationTeam } from "@/types/registration-team.types";
import type { Tournament } from "@/types/tournament.types";

import RegistrationTeamsList from "./RegistrationTeamsList";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listPublic = vi.fn();
const getMyRegistration = vi.fn();
let authStatus = "authenticated";
let authUser: unknown = { id: 1 };

vi.mock("@/hooks/useAuthProfile", () => ({
  useAuthProfile: () => ({ status: authStatus, user: authUser })
}));
vi.mock("@/services/registration-team.service", () => ({
  default: { listPublic: (...args: unknown[]) => listPublic(...args) }
}));
vi.mock("@/services/registration.service", () => ({
  default: { getMyRegistration: (...args: unknown[]) => getMyRegistration(...args) }
}));

const TOURNAMENT = { id: 5, workspace_id: 1, name: "Autumn Cup" } as unknown as Tournament;

function team(overrides: Partial<RegistrationTeam>): RegistrationTeam {
  return {
    id: 1,
    tournament_id: 5,
    name: "Team",
    image_url: null,
    status: "forming",
    captain_registration_id: 100,
    exported_team_id: null,
    members: [],
    invites: [],
    open_slots: { dps: 1 },
    shortfall: "1x dps",
    is_complete: false,
    substitutes_used: 0,
    max_substitutes: 0,
    ...overrides
  } as unknown as RegistrationTeam;
}

async function mount(): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  await act(async () => {
    createRoot(container).render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <RegistrationTeamsList tournament={TOURNAMENT} />
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
  getMyRegistration.mockReset().mockResolvedValue(null);
  listPublic.mockReset();
  document.body.innerHTML = "";
});

describe("registered teams list own-team dedup", () => {
  it("excludes the viewer's own team, already shown above by MyTeamPanel", async () => {
    getMyRegistration.mockResolvedValue({ team: { id: 1 } });
    listPublic.mockResolvedValue({ items: [team({ id: 1, name: "Mine" })], unassigned_players: 0 });

    const container = await mount();

    expect(container.textContent).not.toContain("Mine");
  });

  it("disappears entirely when the only registered team is the viewer's own", async () => {
    getMyRegistration.mockResolvedValue({ team: { id: 1 } });
    listPublic.mockResolvedValue({ items: [team({ id: 1, name: "Mine" })], unassigned_players: 0 });

    const container = await mount();

    expect(container.textContent).toBe("");
  });

  it("still shows other teams once the viewer's own is filtered out", async () => {
    getMyRegistration.mockResolvedValue({ team: { id: 1 } });
    listPublic.mockResolvedValue({
      items: [team({ id: 1, name: "Mine" }), team({ id: 2, name: "Rivals" })],
      unassigned_players: 0
    });

    const container = await mount();

    expect(container.textContent).toContain("Rivals");
    expect(container.textContent).not.toContain("Mine");
    // The count next to the heading reflects what is actually rendered below
    // it, not the tournament-wide total — showing "2 teams" over one visible
    // card would read as a bug, not as "one of them is yours".
    expect(container.textContent).toContain("1 team");
  });

  it("shows every team for a viewer with no registration of their own", async () => {
    authStatus = "unauthenticated";
    authUser = null;
    listPublic.mockResolvedValue({
      items: [team({ id: 1, name: "Alpha" }), team({ id: 2, name: "Beta" })],
      unassigned_players: 0
    });

    const container = await mount();

    expect(container.textContent).toContain("Alpha");
    expect(container.textContent).toContain("Beta");
    expect(getMyRegistration).not.toHaveBeenCalled();
  });
});

describe("registered teams list open slots", () => {
  it("draws one row per slot nobody has taken", async () => {
    // The shortfall used to be a sentence under a roster of glyphs, which left a
    // one-player card stretched to the height of a full one and made the one
    // question this section answers ("where can I still join?") the only thing
    // you had to read instead of see.
    authStatus = "unauthenticated";
    authUser = null;
    listPublic.mockResolvedValue({
      items: [team({ id: 2, name: "Short", open_slots: { dps: 2, support: 1 } })],
      unassigned_players: 0
    });

    const container = await mount();
    const openRows = [...container.querySelectorAll("li")].filter(
      (row) => row.textContent === "Open"
    );
    expect(openRows).toHaveLength(3);
    // The old footer sentence is gone with it, not printed twice.
    expect(container.textContent).not.toContain("Still needed");
  });
});
