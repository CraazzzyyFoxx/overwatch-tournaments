import { describe, expect, it } from "vitest";

import type { PickupVariant } from "@/app/balancer/mix/pickup-lineup";
import type { DraftBoard, DraftPickOptionsResponse, DraftPlayer } from "@/types/draft.types";
import type { PickBanEntry, PickBanState } from "@/types/tournament.types";

import { draftRoomTeams, lineupRoomTeams, poolPlayers, withHeroRoom } from "./room-model";

const DIM = "player_role";

function player(id: number, overrides: Partial<DraftPlayer> = {}): DraftPlayer {
  return {
    id,
    session_id: 1,
    registration_id: null,
    user_id: null,
    workspace_member_id: 100 + id,
    identity: null,
    player_name: `p${id}`,
    primary_role: { dimension: DIM, role: "damage" },
    is_flex: false,
    effective_rank: 1000 + id,
    status: "available",
    is_captain: false,
    drafted_by_team_id: null,
    captain_role: null,
    secondary_roles: [],
    role_ranks: { damage: 1000 + id },
    role_sources: {},
    role_top_characters: {},
    role_sub_roles: {},
    notes: null,
    custom_fields: [],
    version: 0,
    ...overrides
  };
}

function board(players: DraftPlayer[], picks: Partial<DraftBoard["picks"][number]>[] = []): DraftBoard {
  return {
    session: {
      id: 1,
      status: "live",
      roster_shape: { dimension: DIM, slots: { tank: 1, damage: 2 }, team_size: 3, flex_slots: 0, has_role_slots: true }
    },
    // Out of position order on purpose: the room orders teams by their pick position.
    teams: [
      { id: 20, name: "Second", draft_position: 2 },
      { id: 10, name: "First", draft_position: 1 }
    ],
    picks: picks.map((pick, index) => ({ id: index + 1, overall_no: index + 1, status: "completed", ...pick })),
    players,
    current_pick: null
  } as unknown as DraftBoard;
}

const variant = (seats: [string, string][][]): PickupVariant =>
  ({
    teams: seats.map((team, index) => ({
      id: index + 1,
      name: `Team ${index + 1}`,
      averageRank: null,
      captainUuid: null,
      seats: team.map(([uuid, name]) => ({
        uuid,
        name,
        role: "damage",
        rating: 1000,
        openRating: null,
        offRole: false,
        isFlex: false,
        isCaptain: false,
        subRole: null
      }))
    })),
    stats: {},
    benched: []
  }) as unknown as PickupVariant;

function entry(id: number, overrides: Partial<PickBanEntry>): PickBanEntry {
  return {
    id,
    item_id: id,
    round: 1,
    order: 0,
    action_index: null,
    picked_by_kind: null,
    picked_by_team_id: null,
    protected_by_kind: null,
    protected_by_team_id: null,
    status: "available",
    carried_from_round: null,
    picked_for_member_id: null,
    ...overrides
  };
}

describe("draftRoomTeams", () => {
  it("lays each roster over the shape in pick position order, captain first, open slots left empty", () => {
    const teams = draftRoomTeams(
      board(
        [
          player(1, { is_captain: true, drafted_by_team_id: 10, status: "picked", captain_role: { dimension: DIM, role: "tank" }, role_ranks: { tank: 1500 } }),
          player(2, { is_captain: true, drafted_by_team_id: 20, status: "picked" }),
          player(3, { drafted_by_team_id: 10, status: "picked" }),
          player(4)
        ],
        [{ draft_team_id: 10, picked_player_id: 3, target_role: { dimension: DIM, role: "damage" } }]
      ),
      ["Bright Wolves", "Quiet Foxes"]
    );

    expect(teams.map((team) => team.name)).toEqual(["Bright Wolves", "Quiet Foxes"]);
    expect(teams[0].slots.map((slot) => [slot.role, slot.seat?.name ?? null])).toEqual([
      ["tank", "p1"],
      ["damage", "p3"],
      ["damage", null]
    ]);
    expect(teams[0].slots[0].seat).toMatchObject({ isCaptain: true, memberId: 101, key: "m101", rank: 1500 });
    expect(teams[1].slots.filter((slot) => slot.seat != null)).toHaveLength(1);
  });
});

describe("withHeroRoom", () => {
  const state = (pool: PickBanEntry[]): PickBanState =>
    ({
      pool,
      members: [
        { id: 501, encounter_team_id: 71, name: "Ana", workspace_member_id: 11 },
        { id: 601, encounter_team_id: 72, name: "Bo" }
      ],
      starting_sides: [{ game_id: 1, position: 1, sides: { "71": "blue", "72": "red" } }]
    }) as unknown as PickBanState;
  // Out of slot order on purpose: the first live seat is the left lineup team.
  const seats = [
    { id: 72, slot: 2, name: "Quiet Foxes" },
    { id: 71, slot: 1, name: "Bright Wolves" }
  ];
  const lineup = lineupRoomTeams(
    variant([
      [["11", "Ana renamed"]],
      [["12", "Bo"]]
    ])
  );

  it("gives each team its bans in the order they landed, each player their hero, and the side it starts on", () => {
    const teams = withHeroRoom(
      lineup,
      state([
        entry(1, { status: "banned", picked_by_team_id: 72, action_index: 1 }),
        entry(2, { status: "banned", picked_by_team_id: 71, action_index: 0 }),
        entry(3, { status: "banned", picked_by_team_id: 71, action_index: 2 }),
        // Tied to the seat by workspace member, whatever the room calls the player.
        entry(4, { status: "picked", picked_by_team_id: 71, picked_for_member_id: 501, action_index: 3 }),
        // No workspace member on the room's side: the name still finds the seat.
        entry(5, { status: "picked", picked_by_team_id: 72, picked_for_member_id: 601, action_index: 4 }),
        // A captain's pick nobody holds yet.
        entry(6, { status: "picked", picked_by_team_id: 72, action_index: 5 }),
        entry(7, {})
      ]),
      seats
    );

    expect(teams.map((team) => team.bans)).toEqual([[2, 3], [1]]);
    expect(teams.map((team) => team.slots[0].seat?.heroId)).toEqual([4, 5]);
    // The seat's player in the room, which a roster click picks for.
    expect(teams.map((team) => team.slots[0].seat?.teamMemberId)).toEqual([501, 601]);
    expect(teams.map((team) => team.unassignedPicks)).toEqual([[], [6]]);
    expect(teams.map((team) => team.side)).toEqual(["blue", "red"]);
  });

  it("leaves the teams as they are without a hero room", () => {
    expect(withHeroRoom(lineup, null, seats)).toEqual(lineup);
  });
});

describe("poolPlayers", () => {
  const live = board([player(1, { effective_rank: 900 }), player(2, { effective_rank: 1900 }), player(3, { status: "picked" })]);
  const withPick = { ...live, current_pick: { id: 7 } } as unknown as DraftBoard;
  const options = (pickId: number): DraftPickOptionsResponse => ({
    pick_id: pickId,
    pick_version: 0,
    draft_team_id: 10,
    options: [
      { player_id: 1, role: { dimension: DIM, role: "damage" }, is_safe: true, reason_code: null, unmatched_slots: [], blocking_player_ids: [] },
      { player_id: 2, role: { dimension: DIM, role: "damage" }, is_safe: false, reason_code: "role_shortage", unmatched_slots: [], blocking_player_ids: [] }
    ]
  });

  it("lists who is still available, strongest first, with the roles the pick may seat them on or why not", () => {
    expect(poolPlayers(withPick, options(7)).map((row) => [row.player.id, row.roles, row.reason])).toEqual([
      [2, [], "role_shortage"],
      [1, ["damage"], null]
    ]);
  });

  it("gives no verdict on options read for an earlier pick", () => {
    expect(poolPlayers(withPick, options(6)).map((row) => [row.player.id, row.roles, row.reason])).toEqual([
      [2, [], null],
      [1, [], null]
    ]);
  });
});
