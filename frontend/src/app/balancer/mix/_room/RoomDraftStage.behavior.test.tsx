// @vitest-environment happy-dom
//
// The captains' draft in the room's centre (spec §9.3, §7.5 A2/D1): a host starts it, the captain on the clock is
// alerted in the tab, picks a player from the pool on a role the server allows, and sees why a player cannot be
// picked. Mounted the way the room mounts it (board query, gating, pick options, draft writes) over a fake server.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OW_OWNER, OW_SHAPE } from "@/app/balancer/mix/mix-owner.fixture";
import en from "@/i18n/messages/en.json";
import { useDraftBoardQuery, useDraftMutations, useDraftPickOptionsQuery } from "@/hooks/useDraftData";
import { computeGating } from "@/lib/draft/logic";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import type { DraftBoard, DraftLifecycleAction, DraftPickOptionsResponse, DraftPlayer } from "@/types/draft.types";

import { RoomDraftStage } from "./RoomDraftStage";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let server: DraftBoard;
let options: DraftPickOptionsResponse;
const select = vi.fn();
vi.mock("@/services/draft.service", () => ({
  default: {
    getSessionBoard: async () => server,
    getPickOptions: async () => options,
    select: (...args: unknown[]) => select(...args),
    lifecycle: async (sessionId: number, action: DraftLifecycleAction) => {
      if (sessionId === 31 && action === "start") server = draft("live", false);
      return server.session;
    },
  },
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), apiError: vi.fn() } }));

const VIEWER = { id: 70, playerIds: [7] };

function player(id: number, overrides: Partial<DraftPlayer>): DraftPlayer {
  return {
    id,
    session_id: 31,
    registration_id: null,
    user_id: null,
    workspace_member_id: 100 + id,
    identity: null,
    player_name: `p${id}`,
    primary_role: { dimension: OW_SHAPE.dimension ?? "player_role", role: "damage" },
    is_flex: false,
    effective_rank: 2000 + id,
    status: "available",
    is_captain: false,
    drafted_by_team_id: null,
    captain_role: null,
    secondary_roles: [],
    role_ranks: { damage: 2000 + id },
    role_sources: {},
    role_top_characters: {},
    role_sub_roles: {},
    notes: null,
    custom_fields: [],
    version: 0,
    ...overrides,
  };
}

/** Two teams, team 10 on the clock once live; `mine` makes the viewer (account 70, player 7) its captain. */
function draft(status: "ready" | "live", mine: boolean): DraftBoard {
  const pick = {
    id: 1,
    session_id: 31,
    overall_no: 1,
    round_no: 1,
    pick_in_round: 1,
    draft_team_id: 10,
    target_role: null,
    target_rank_value: null,
    status: status === "live" ? "on_clock" : "upcoming",
    picked_player_id: null,
    picked_by_user_id: null,
    is_autopick: false,
    is_admin_override: false,
    clock_started_at: null,
    clock_expires_at: null,
    overtime_started_at: null,
    version: 4,
  };
  return {
    session: {
      id: 31,
      status,
      current_pick_id: status === "live" ? 1 : null,
      roster_shape: OW_SHAPE,
      blocked_reason: null,
    },
    teams: [
      { id: 10, session_id: 31, name: "Bravo", captain_auth_user_id: mine ? 70 : 80, captain_user_id: mine ? 7 : 8, draft_position: 1, exported_team_id: null },
      { id: 11, session_id: 31, name: "Alpha", captain_auth_user_id: 81, captain_user_id: 9, draft_position: 2, exported_team_id: null },
    ],
    picks: [pick],
    players: [
      player(1, { player_name: "bravo", is_captain: true, drafted_by_team_id: 10, status: "picked" }),
      player(2, { player_name: "alpha", is_captain: true, drafted_by_team_id: 11, status: "picked" }),
      player(3, { player_name: "charlie" }),
      player(4, { player_name: "delta", primary_role: { dimension: OW_SHAPE.dimension ?? "player_role", role: "tank" }, role_ranks: { tank: 2400 } }),
    ],
    current_pick: status === "live" ? pick : null,
    last_event_id: 0,
  } as unknown as DraftBoard;
}

function Stage({ canHost }: Readonly<{ canHost: boolean }>) {
  const board = useDraftBoardQuery(31).data ?? null;
  const mutations = useDraftMutations(tournamentQueryKeys.draftSessionBoard(31));
  const gating = board != null ? computeGating(board, VIEWER.playerIds, VIEWER.id, false) : null;
  const pickOptions = useDraftPickOptionsQuery(board?.current_pick?.id ?? null, gating?.isMyPick === true);
  if (board == null || gating == null) return null;
  return (
    <RoomDraftStage
      board={board}
      teamNames={["Bravo", "Alpha"]}
      owner={OW_OWNER}
      gating={gating}
      options={gating.isMyPick ? (pickOptions.data ?? null) : null}
      connectionState="connected"
      mutations={mutations}
      canHost={canHost}
      myMemberId={null}
      waiting={[]}
      adding={false}
      onAddPlayer={vi.fn()}
    />
  );
}

let container: HTMLDivElement;
let root: Root;

async function settle(ticks = 3) {
  for (let index = 0; index < ticks; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount(canHost: boolean) {
  await act(async () => {
    root.render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          <Stage canHost={canHost} />
        </NextIntlClientProvider>
      </QueryClientProvider>,
    );
  });
  await settle();
}

function button(name: string) {
  return [...document.body.querySelectorAll("button")].find((candidate) => candidate.textContent?.trim() === name) ?? null;
}

const card = (name: string) =>
  [...container.querySelectorAll("li")].find((item) => item.textContent?.includes(name)) ?? null;

beforeEach(() => {
  document.title = "Mix";
  select.mockReset();
  options = {
    pick_id: 1,
    pick_version: 4,
    draft_team_id: 10,
    options: [
      { player_id: 3, role: { dimension: OW_SHAPE.dimension ?? "player_role", role: "damage" }, is_safe: true, reason_code: null, unmatched_slots: [], blocking_player_ids: [] },
      { player_id: 4, role: { dimension: OW_SHAPE.dimension ?? "player_role", role: "tank" }, is_safe: false, reason_code: "slot_filled", unmatched_slots: [], blocking_player_ids: [] },
    ],
  };
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("RoomDraftStage", () => {
  it("lets a host start the seeded draft", async () => {
    server = draft("ready", false);
    await mount(true);
    expect(container.textContent).toContain(en.mixes.arena.draft.setupHintHost);

    await act(async () => button(en.mixes.draft.startDraft)?.click());
    await settle();

    expect(button(en.mixes.draft.startDraft)).toBeNull();
    expect(container.textContent).toContain("Bravo is picking");
  });

  it("gives a viewer no host control", async () => {
    server = draft("ready", false);
    await mount(false);

    expect(container.textContent).toContain(en.mixes.arena.draft.setupHint);
    expect(button(en.mixes.draft.startDraft)).toBeNull();
  });

  it("puts the captain's own turn in the tab title", async () => {
    server = draft("live", true);
    await mount(false);

    expect(document.title).toBe(en.mixes.draft.yourPickTitle);
  });

  it("picks the chosen player on the role the server allows for this pick", async () => {
    server = draft("live", true);
    select.mockImplementation(async () => server.current_pick);
    await mount(false);

    expect(button("Pick charlie")).toBeNull();
    await act(async () => card("charlie")?.querySelector("button")?.click());
    await act(async () => button("Pick charlie")?.click());
    await settle();

    expect(select).toHaveBeenCalledWith(1, {
      player_id: 3,
      expected_version: 4,
      target_role: { dimension: OW_SHAPE.dimension, role: "damage" },
    });
  });

  it("says why the team cannot take a player now, and offers no pick of them", async () => {
    server = draft("live", true);
    await mount(false);

    const delta = card("delta");
    expect(delta?.textContent).toContain(en.mixes.arena.draft.unpickable.slot_filled);
    expect(delta?.querySelector("button")).toBeNull();
  });
});
