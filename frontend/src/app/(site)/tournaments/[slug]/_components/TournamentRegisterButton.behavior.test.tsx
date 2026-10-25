// @vitest-environment happy-dom
//
// The hero's action slot once registration has closed: the closed state while
// a latecomer could still be looking for the sign-up, a registered viewer's own
// status until the matches start, and otherwise nothing — never a dead,
// button-shaped box on a tournament that stopped asking for sign-ups.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Tournament, TournamentStatus } from "@/types/tournament.types";

import TournamentRegisterButton from "./TournamentRegisterButton";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getForm = vi.fn();
const getMyRegistration = vi.fn();
let auth: { status: string; user: unknown };

vi.mock("@/services/registration.service", () => ({
  default: {
    getForm: (...args: unknown[]) => getForm(...args),
    getMyRegistration: (...args: unknown[]) => getMyRegistration(...args)
  }
}));
vi.mock("@/hooks/useAuthProfile", () => ({ useAuthProfile: () => auth }));
vi.mock("@/stores/auth-modal.store", () => ({ useAuthModalStore: () => () => {} }));
// What the OPEN slot renders; this file is about the closed one.
vi.mock("@/components/registration/RegistrationWizard", () => ({ default: () => null }));
vi.mock("@/components/registration/TeamRegistrationEntry", () => ({ default: () => null }));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    prefetch: _prefetch,
    ...rest
  }: { href: string; children: React.ReactNode; prefetch?: boolean | null } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

function makeTournament(status: TournamentStatus): Tournament {
  return {
    id: 88,
    created_at: new Date(0),
    updated_at: null,
    workspace_id: 3,
    name: "Anak Cup",
    slug: "anak-cup",
    start_date: new Date("2024-08-12T10:00:00Z"),
    end_date: new Date("2024-08-13T22:00:00Z"),
    description: null,
    rules: null,
    challonge_id: null,
    challonge_slug: null,
    is_league: false,
    is_finished: false,
    is_hidden: false,
    team_formation: "balancer",
    status,
    auto_transitions_enabled: true,
    allow_late_registration: false,
    discord_broadcasts_enabled: false,
    discord_dms_enabled: false,
    logs_official: false,
    pov_stream_delay_s: 0,
    // Registration closed long ago, whatever the status says.
    phase_schedule: [
      {
        status: "registration",
        starts_at: "2024-08-01T10:00:00.000Z",
        ends_at: "2024-08-10T10:00:00.000Z"
      }
    ],
    win_points: 1,
    draw_points: 0.5,
    loss_points: 0,
    stages: [],
    participants_count: 70,
    registrations_count: 75,
    teams_count: 14,
    division_grid_version_id: null,
    division_grid_version: null,
    discipline: "overwatch",
    identity_provider: "battlenet",
    draft_format_json: null,
    roster_shape: null,
    roster_locked_by_draft: null,
    links: [],
    cover_image_url: null,
    logo_url: null
  };
}

let container: HTMLDivElement;
let root: Root;
let client: QueryClient;

beforeEach(() => {
  vi.clearAllMocks();
  getForm.mockResolvedValue({ id: 1 });
  getMyRegistration.mockResolvedValue(null);
  auth = { status: "anonymous", user: undefined };
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function mount(tournament: Tournament) {
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          <TournamentRegisterButton tournament={tournament} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  for (let tick = 0; tick < 4; tick += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

describe("the action slot once registration has closed", () => {
  it("says so while a latecomer could still be looking for the sign-up", async () => {
    await mount(makeTournament("check_in"));

    expect(container.textContent).toBe(en.registration.button.closed);
  });

  it("says nothing once the teams are being formed", async () => {
    await mount(makeTournament("draft"));

    expect(container.textContent).toBe("");
  });

  it("shows a registered viewer their own status instead, until the matches start", async () => {
    auth = { status: "authenticated", user: { id: 1 } };
    getMyRegistration.mockResolvedValue({ status: "approved" });

    await mount(makeTournament("draft"));
    const link = container.querySelector("a");
    expect(link?.textContent).toBe(en.common.approved);
    expect(link?.getAttribute("href")).toBe("/tournaments/anak-cup/participants");

    await mount(makeTournament("live"));
    expect(container.textContent).toBe("");
  });
});
