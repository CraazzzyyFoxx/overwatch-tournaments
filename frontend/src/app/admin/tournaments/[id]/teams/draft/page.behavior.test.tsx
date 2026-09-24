// @vitest-environment happy-dom
//
// The Teams › Draft sub-tab. What is pinned here:
//  1. `Draft` is not a permission but a tournament property: a balancer
//     tournament neither shows the tab nor can reach the route by URL — a
//     hidden-but-reachable sub-tab is precisely the bug the guard exists for;
//  2. the phase strip states which of Setup · Ready · Live · Done the session
//     is in, because this one URL renders either the setup wizard or the live
//     control room and used to say nothing about which;
//  3. `paused` is still Live, and a session nobody has created yet is Setup.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DraftStatus } from "@/types/draft.types";

import TeamsLayout from "../layout";
import TeamsDraftPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Hoisted: these factories run while the module graph is still initializing,
// so they cannot close over ordinary top-level consts.
const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getTournamentBoard: vi.fn(),
  dashboardMounts: [] as number[],
  pathname: "/admin/tournaments/64/teams/draft",
  teamFormation: "draft" as "balancer" | "draft"
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "64" }),
  usePathname: () => mocks.pathname,
  useRouter: () => ({ replace: mocks.replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams()
}));

// A bare anchor: the app-router context next/link needs is not mounted, and
// every prop the tab row passes is valid on `<a>`.
vi.mock("next/link", () => ({ default: "a" }));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ canAccessPermission: () => true, isLoaded: true })
}));

vi.mock("../../hubQueries", () => ({
  tabFallback: null,
  useHubTournamentQuery: () => ({
    data: { id: 64, workspace_id: 1, team_formation: mocks.teamFormation },
    isLoading: false
  })
}));

vi.mock("@/services/draft.service", () => ({
  default: { getTournamentBoard: mocks.getTournamentBoard }
}));

// The dashboard branches into the wizard or the control room, each with its own
// realtime and mutation wiring; the page's own contract is the phase above them.
vi.mock("../../components/DraftSessionDashboard", () => ({
  DraftSessionDashboard: (props: { tournamentId: number }) => {
    mocks.dashboardMounts.push(props.tournamentId);
    return null;
  }
}));

let container: HTMLElement;
let root: Root;

async function settle() {
  // Macrotasks, not a bare microtask: the board query and `next/dynamic`'s
  // lazy import both resolve through the timer queue.
  for (let turn = 0; turn < 4; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function render(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  await act(async () => {
    root.render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
  });
  await settle();
}

function currentPhase() {
  return container.querySelector("[aria-current='step']")?.textContent?.trim();
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  mocks.replace.mockReset();
  mocks.getTournamentBoard.mockReset().mockResolvedValue(null);
  mocks.dashboardMounts.length = 0;
  mocks.pathname = "/admin/tournaments/64/teams/draft";
  mocks.teamFormation = "draft";
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("teams sub-tab bar", () => {
  it("offers Draft and renders it for a drafting tournament", async () => {
    await render(<TeamsLayout>{<div data-testid="body" />}</TeamsLayout>);

    const tabs = [...container.querySelectorAll("a[data-link-tab]")].map((tab) => tab.textContent);
    expect(tabs).toEqual(["Roster", "Draft"]);
    expect(container.querySelector("[data-testid='body']")).toBeTruthy();
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it("hides Draft for a balancer tournament and bounces the route to Roster", async () => {
    mocks.teamFormation = "balancer";

    await render(<TeamsLayout>{<div data-testid="body" />}</TeamsLayout>);

    const tabs = [...container.querySelectorAll("a[data-link-tab]")].map((tab) => tab.textContent);
    expect(tabs).toEqual(["Roster"]);
    // Not merely hidden: the body is withheld and the URL corrected, so a
    // pasted link cannot open a draft on a tournament that has none.
    expect(container.querySelector("[data-testid='body']")).toBeNull();
    expect(mocks.replace).toHaveBeenCalledWith("/admin/tournaments/64/teams/roster");
  });

  it("leaves the roster segment alone for a balancer tournament", async () => {
    mocks.teamFormation = "balancer";
    mocks.pathname = "/admin/tournaments/64/teams/roster";

    await render(<TeamsLayout>{<div data-testid="body" />}</TeamsLayout>);

    expect(container.querySelector("[data-testid='body']")).toBeTruthy();
    expect(mocks.replace).not.toHaveBeenCalled();
  });
});

describe("draft phase strip", () => {
  it("stands at Setup while no session exists", async () => {
    await render(<TeamsDraftPage />);

    expect(currentPhase()).toBe("Setup");
    expect(mocks.dashboardMounts).toContain(64);
  });

  it.each([
    ["setup", "Setup"],
    ["ready", "Ready"],
    ["live", "Live"],
    // A paused draft is a running one waiting on the organizer, not its own phase.
    ["paused", "Live"],
    ["completed", "Done"],
    // Cancelled leaves a fresh wizard on screen, so the strip says Setup too.
    ["cancelled", "Setup"]
  ] as [DraftStatus, string][])("reflects session status %s as %s", async (status, label) => {
    mocks.getTournamentBoard.mockResolvedValue({ session: { id: 3, status } });

    await render(<TeamsDraftPage />);

    expect(currentPhase()).toBe(label);
  });

  it("names all four phases in lifecycle order", async () => {
    mocks.getTournamentBoard.mockResolvedValue({ session: { id: 3, status: "live" } });

    await render(<TeamsDraftPage />);

    const phases = [...container.querySelectorAll("ol[aria-label='Phases'] li")].map((item) =>
      item.textContent?.trim()
    );
    expect(phases).toEqual(["Setup", "Ready", "Live", "Done"]);
  });
});
