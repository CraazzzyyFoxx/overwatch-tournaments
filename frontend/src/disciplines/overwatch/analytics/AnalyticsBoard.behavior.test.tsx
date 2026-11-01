// @vitest-environment happy-dom
//
// Overwatch's analytics board (the `analytics` slot), fed the real captured analytics-service responses of two
// tournaments. Switching tournament never keeps the previous one's rankings or result on screen, and never asks for
// the new tournament's result before its own ranking list has confirmed the chosen algorithm.
import fs from "node:fs";
import path from "node:path";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import type { SlotProps } from "@/disciplines/types";
import { OW_METADATA } from "@/test/discipline-metadata";
import type { AlgorithmAnalytics, TournamentAnalytics } from "@/types/analytics.types";

import AnalyticsBoard from "./AnalyticsBoard";

const nav = vi.hoisted(() => ({
  params: new URLSearchParams(),
  replace: vi.fn(),
  push: vi.fn()
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: nav.push }),
  usePathname: () => "/tournaments/analytics",
  useSearchParams: () => nav.params
}));

const api = vi.hoisted(() => ({
  getAlgorithms: vi.fn(),
  getAnalytics: vi.fn(),
  getPerformanceV2: vi.fn(),
  getStandingsDistribution: vi.fn()
}));
vi.mock("@/services/analytics.service", () => ({ default: api }));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ hasPermission: () => false, canAccessPermission: () => false, isSuperuser: false })
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

interface Capture {
  input_old_wire: {
    analytics: { body: TournamentAnalytics };
    algorithms: { body: { results: AlgorithmAnalytics[] } };
  };
}
const FIXTURES = path.join(__dirname, "..", "__fixtures__", "pre-move");
const capture = (name: string) =>
  JSON.parse(fs.readFileSync(path.join(FIXTURES, name), "utf8")) as Capture;
const MAIN = capture("analytics.tournament.linear.json");
const OTHER = capture("analytics.tournament_other.linear.json");
/** The frozen capture predates `display`: with no game override a roster row is shown under its own name. */
const withDisplay = (body: TournamentAnalytics): TournamentAnalytics => ({
  ...body,
  teams: body.teams.map((team) => ({
    ...team,
    players: team.players.map((player) => ({
      ...player,
      display: { name: player.name, tag: null, canonical: player.name, snapshot: null }
    }))
  }))
});
const TOURNAMENT = 910_000;
const OTHER_TOURNAMENT = 910_001;

let root: Root | null = null;
let container: HTMLElement;
let client: QueryClient;

async function settle() {
  for (let turn = 0; turn < 6; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

function board(tournamentId: number, workspaceId: number) {
  const props: SlotProps["analytics"] = {
    tournamentId,
    workspaceId,
    metadata: OW_METADATA,
    canReadV2: false,
    canUpdate: false,
    ended: true,
    hero: (parts) => (
      <header data-testid="hero" data-teams={parts.counts?.teams ?? ""}>
        {parts.controls}
      </header>
    )
  };
  return (
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={messages}>
        <AnalyticsBoard {...props} />
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
}

async function render(tournamentId: number, workspaceId: number, query: string) {
  nav.params = new URLSearchParams(query);
  await act(async () => {
    root ??= createRoot(container);
    root.render(board(tournamentId, workspaceId));
  });
  await settle();
}

const hero = () => container.querySelector<HTMLElement>("[data-testid=hero]");
/** The board's ranking picker, which it hands to the host's hero. */
const rankingPicker = () => hero()?.querySelector<HTMLElement>('[role="combobox"][aria-label="Algorithm"]') ?? null;

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  container = document.createElement("div");
  document.body.appendChild(container);
  for (const fn of [...Object.values(api), nav.replace, nav.push]) fn.mockReset();
  api.getAnalytics.mockImplementation(async (tournamentId: number) =>
    withDisplay((tournamentId === TOURNAMENT ? MAIN : OTHER).input_old_wire.analytics.body)
  );
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container.remove();
});

describe("Overwatch analytics board", () => {
  it("shows the tournament's result for the ranking named in the URL, through the host's hero", async () => {
    api.getAlgorithms.mockResolvedValue(MAIN.input_old_wire.algorithms.body);

    await render(TOURNAMENT, 910_000, `tournamentId=${TOURNAMENT}&algorithm=2`);

    expect(api.getAnalytics).toHaveBeenCalledWith(TOURNAMENT, 2, 910_000, expect.objectContaining({ signal: expect.anything() }));
    expect(container.textContent).toContain("P4 team_home");
    expect(rankingPicker()?.textContent).toBe("Linear");
    expect(hero()?.dataset.teams).toBe(String(MAIN.input_old_wire.analytics.body.summary.total_teams));
    expect(api.getPerformanceV2).not.toHaveBeenCalled();
    // Roles come from the owner metadata the host handed in (the analytics DTO's nested tournament has no owner
    // scope): roster glyphs are the known Overwatch roles, named — never the neutral unknown mark.
    expect(container.querySelector('[role="img"][aria-label="Support"]')).not.toBeNull();
    expect(container.querySelector('[role="img"][aria-label^="Unknown"]')).toBeNull();
  });

  it("drops the previous tournament's board and waits for the new one's own rankings before reading its result", async () => {
    api.getAlgorithms.mockResolvedValueOnce(MAIN.input_old_wire.algorithms.body);
    await render(TOURNAMENT, 910_000, `tournamentId=${TOURNAMENT}&algorithm=2`);
    expect(container.textContent).toContain("P4 team_home");

    const other = Promise.withResolvers<{ results: AlgorithmAnalytics[] }>();
    api.getAlgorithms.mockReturnValueOnce(other.promise);
    await render(OTHER_TOURNAMENT, 910_001, `tournamentId=${OTHER_TOURNAMENT}&algorithm=2`);

    // Pending: nothing of the first tournament stands in, and its algorithm id is not trusted yet.
    expect(container.textContent).not.toContain("P4 team_home");
    expect(rankingPicker()).toBeNull();
    expect(hero()?.dataset.teams).toBe("");
    expect(api.getAnalytics).not.toHaveBeenCalledWith(OTHER_TOURNAMENT, expect.anything(), expect.anything(), expect.anything());

    await act(async () => other.resolve(OTHER.input_old_wire.algorithms.body));
    await settle();

    expect(api.getAnalytics).toHaveBeenLastCalledWith(OTHER_TOURNAMENT, 2, 910_001, expect.anything());
    expect(container.textContent).toContain("P4 team_other_home");
    expect(container.textContent).not.toContain("P4 team_home");
  });

  it("replaces a ranking this tournament does not offer with its preferred one, without reading it", async () => {
    api.getAlgorithms.mockResolvedValue(MAIN.input_old_wire.algorithms.body);

    await render(TOURNAMENT, 910_000, `tournamentId=${TOURNAMENT}&algorithm=99`);

    expect(nav.replace).toHaveBeenCalledWith(`/tournaments/analytics?tournamentId=${TOURNAMENT}&algorithm=2`);
    expect(api.getAnalytics).not.toHaveBeenCalled();
    expect(nav.push).not.toHaveBeenCalled();
  });
});
