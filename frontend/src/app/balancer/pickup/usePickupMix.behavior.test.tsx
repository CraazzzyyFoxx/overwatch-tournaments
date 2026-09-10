// @vitest-environment happy-dom
//
// Adding a player to a mix seeds that player's effective rank into the host's
// own book server-side (`_seed_host_ranks`), so the "My ranks" list and chip
// count in the add-players dialog go stale the moment `setRoster` succeeds
// unless the workspace-player cache is invalidated too. Pinned here rather
// than in the dialog's own test because the dialog never calls `setRoster` --
// that mutation lives in this hook, one level up.
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { usePickupMix } from "./usePickupMix";

const updateRoster = vi.fn();
const updatePlayer = vi.fn();
const setParticipation = vi.fn();
const listGames = vi.fn();
const getGame = vi.fn();
const listMatches = vi.fn();
const rotation = vi.fn();

vi.mock("@/services/custom-game.service", () => ({
  customGameKeys: {
    all: (workspaceId: number) => ["custom-games", workspaceId],
    list: (workspaceId: number) => ["custom-games", workspaceId],
    one: (workspaceId: number, gameId: number) => ["custom-games", workspaceId, gameId],
    matches: (workspaceId: number, gameId: number) => ["custom-games", workspaceId, gameId, "matches"],
    rotation: (workspaceId: number, gameId: number) => ["custom-games", workspaceId, gameId, "rotation"],
  },
  customGameService: {
    list: (...args: unknown[]) => listGames(...args),
    get: (...args: unknown[]) => getGame(...args),
    updateRoster: (...args: unknown[]) => updateRoster(...args),
    updatePlayer: (...args: unknown[]) => updatePlayer(...args),
    listMatches: (...args: unknown[]) => listMatches(...args),
    setParticipation: (...args: unknown[]) => setParticipation(...args),
    rotation: (...args: unknown[]) => rotation(...args),
  },
}));

vi.mock("@/services/workspace-player.service", () => ({
  workspacePlayerKeys: {
    all: (workspaceId: number) => ["workspace-players", workspaceId],
  },
}));

type CoalescedOptions = {
  onEvent: (event: { data?: { resources?: string[] } }, schedule: () => void) => void;
  onFlush: () => void;
};
const realtimeCalls: Array<{ topic: unknown } & CoalescedOptions> = [];
// One level below `useInvalidation`, so the hook's own resource bookkeeping is
// exercised while the websocket is not.
vi.mock("@/hooks/useRealtimeCoalescedRefetch", () => ({
  useRealtimeCoalescedRefetch: (topic: unknown, options: CoalescedOptions) => {
    realtimeCalls.push({ topic, ...options });
  },
}));

vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), apiError: vi.fn() } }));

const WORKSPACE_ID = 7;
const GAME_ID = 11;


/** The mix's own settings, all at their defaults. */
const SETTINGS = {
  points_per_win: null,
  team_names: {},
  role_mask: null,
  balancer_config: null,
};

function game(overrides: Record<string, unknown> = {}) {
  return {
    id: GAME_ID,
    workspace_id: WORKSPACE_ID,
    host_user_id: 1,
    co_hosts: [],
    host_display_name: null,
    name: "Tonight",
    status: "draft",
    settings: SETTINGS,
    balance_result: null,
    created_at: null,
    roster_shape: null,
    ...overrides,
  };
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

/** Exposes the hook's `setRoster`/`applyRotationHints` mutations and the shared `QueryClient` to assertions. */
function Harness({
  onReady,
}: {
  onReady: (api: {
    setRoster: (ids: number[]) => void;
    applyRotationHints: () => void;
    client: QueryClient;
  }) => void;
}) {
  const client = useQueryClient();
  const { setRoster, applyRotationHints } = usePickupMix(WORKSPACE_ID, GAME_ID);
  onReady({
    setRoster: (ids) => setRoster.mutate(ids),
    applyRotationHints: () => applyRotationHints.mutate(),
    client,
  });
  return null;
}

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let api: { setRoster: (ids: number[]) => void; applyRotationHints: () => void; client: QueryClient } | null =
    null;
  await act(async () => {
    createRoot(container).render(
      <QueryClientProvider client={client}>
        <Harness onReady={(value) => (api = value)} />
      </QueryClientProvider>,
    );
  });
  await act(async () => {
    await tick();
  });
  if (!api) throw new Error("hook did not render");
  return api;
}

beforeEach(() => {
  document.body.innerHTML = "";
  vi.clearAllMocks();
  realtimeCalls.length = 0;
  listGames.mockResolvedValue([game()]);
  getGame.mockResolvedValue(game({ players: [] }));
  updateRoster.mockResolvedValue(game({ players: [] }));
  listMatches.mockResolvedValue([]);
  rotation.mockResolvedValue([]);
});

describe("usePickupMix", () => {
  it("invalidates the workspace-player cache after updating the roster", async () => {
    const { setRoster, client } = await mount();
    // Seed a cache entry the same way the add-players dialog's queries would,
    // so there is something to observe going stale.
    const playerKey = ["workspace-players", WORKSPACE_ID];
    client.setQueryData(playerKey, { total: 3 });
    expect(client.getQueryState(playerKey)?.isInvalidated).toBe(false);

    await act(async () => {
      setRoster([9]);
      await tick();
      await tick();
    });

    expect(updateRoster).toHaveBeenCalledWith(WORKSPACE_ID, GAME_ID, [9]);
    expect(client.getQueryState(playerKey)?.isInvalidated).toBe(true);
  });

  it("subscribes to this workspace's invalidation topic and refetches both caches on pickup_mix", async () => {
    const { client } = await mount();
    const playerKey = ["workspace-players", WORKSPACE_ID];
    const gameKey = ["custom-games", WORKSPACE_ID];
    client.setQueryData(playerKey, { total: 3 });
    client.setQueryData(gameKey, []);

    // The mock records every render, not every effect run; the topic must be
    // stable across them regardless.
    expect(realtimeCalls.length).toBeGreaterThan(0);
    const latest = realtimeCalls[realtimeCalls.length - 1];
    expect(latest.topic).toBe(`workspace:${WORKSPACE_ID}:invalidation`);

    latest.onEvent({ data: { resources: ["workspace.pickup_mix"] } }, () => {});
    latest.onFlush();

    expect(client.getQueryState(playerKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(gameKey)?.isInvalidated).toBe(true);
  });

  it("applies every rotation hint in one atomic write, then reseeds the caches", async () => {
    getGame.mockResolvedValueOnce(
      game({
        players: [
          {
            id: 1,
            workspace_member_id: 9,
            display_name: null,
            battle_tag: "Aria#1111",
            sort_order: 0,
            participation: "benched",
            role_selection_mode: "all_ranked",
            is_flex: false,
            roles: null,
            ranks: {},
            rank_sources: {},
            author_ranks: {},
          },
        ],
      }),
    );
    rotation.mockResolvedValueOnce([
      {
        workspace_member_id: 9,
        status: "must_play",
        reason: "Owed a seat",
        consecutive_sat: 1,
        consecutive_played: 0,
        games_played: 2,
      },
    ]);
    setParticipation.mockResolvedValue(game({ players: [] }));

    const { applyRotationHints } = await mount();

    await act(async () => {
      applyRotationHints();
      await tick();
      await tick();
      await tick();
    });

    // Owed a seat: one request moves the whole verdict, so there is no
    // per-row race for the cache to reconcile afterwards.
    expect(setParticipation).toHaveBeenCalledTimes(1);
    expect(setParticipation).toHaveBeenCalledWith(WORKSPACE_ID, GAME_ID, [
      { workspace_member_id: 9, participation: "must_play" },
    ]);
    expect(updatePlayer).not.toHaveBeenCalled();
  });

  it("never calls the server when the lineup already matches every hint", async () => {
    getGame.mockResolvedValueOnce(
      game({
        players: [
          {
            id: 1,
            workspace_member_id: 9,
            display_name: null,
            battle_tag: "Aria#1111",
            sort_order: 0,
            participation: "must_play",
            role_selection_mode: "all_ranked",
            is_flex: false,
            roles: null,
            ranks: {},
            rank_sources: {},
            author_ranks: {},
          },
        ],
      }),
    );
    rotation.mockResolvedValueOnce([
      {
        workspace_member_id: 9,
        status: "must_play",
        reason: "Owed a seat",
        consecutive_sat: 1,
        consecutive_played: 0,
        games_played: 2,
      },
    ]);

    const { applyRotationHints } = await mount();

    await act(async () => {
      applyRotationHints();
      await tick();
      await tick();
    });

    expect(setParticipation).not.toHaveBeenCalled();
  });
});
