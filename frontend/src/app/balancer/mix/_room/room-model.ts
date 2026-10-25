import type { PickBanSeat } from "@/components/pick-ban/pick-ban-model";
import { buildTeamViews } from "@/lib/draft/room-model";
import { slotRankForPlayer } from "@/lib/draft/workspace-model";
import { OPEN_SLOT_CODE } from "@/lib/roster/shape";
import type { MixLobbyState } from "@/services/custom-game.service";
import type { DraftBoard, DraftPickOptionsResponse, DraftPlayer } from "@/types/draft.types";
import type { PickBanState } from "@/types/tournament.types";
import { roleOf } from "@/lib/roster/role-ref";

import type { PickupVariant } from "../pickup-lineup";

/** What the room's centre shows: a lobby's stage (spec §5) with the draft's two states folded into one. */
export type RoomPhase = "idle" | "draft" | "ready" | "pregame" | "live";

export function roomPhase(state: MixLobbyState): RoomPhase {
  return state === "draft_setup" || state === "draft_live" ? "draft" : state;
}

/** One player in a team column, whichever source seated them: a draft pick or a lineup seat. */
export interface RoomSeat {
  /** React key and view-transition identity: the workspace member when known, so a pick morphs pool → slot. */
  key: string;
  memberId: number | null;
  name: string;
  /** The role code the seat plays; the open slot (`flex`) or null where the game names none. */
  role: string | null;
  rank: number | null;
  isCaptain: boolean;
  /** The hero picked for this player (a catalogue id); null until one is. */
  heroId: number | null;
  /** This player in the hero room (`PickBanMember.id`); null outside one. */
  teamMemberId: number | null;
}

export interface RoomSlot {
  key: string;
  /** The role an empty slot waits for; null for an open slot. */
  role: string | null;
  seat: RoomSeat | null;
}

export interface RoomTeam {
  name: string;
  averageRank: number | null;
  slots: RoomSlot[];
  /** Heroes this team banned, in the order the room applied them. */
  bans: number[];
  /** Heroes the team took that no player holds yet: a captain's picks before the assignment. */
  unassignedPicks: number[];
  /** The side code this team starts on, once a side step chose it. */
  side: string | null;
}

/** A draft seat's name: its game handle, else the canonical player name, else its number. */
export function draftPlayerName(player: DraftPlayer): string {
  return player.identity?.handle ?? player.player_name ?? `#${player.id}`;
}

function memberSeatKey(memberId: number | null, fallback: string): string {
  return memberId != null ? `m${memberId}` : fallback;
}

/** A lineup seat's identity in the room: its uuid is the workspace member's id on a mix lineup. */
export function lineupSeatKey(uuid: string): string {
  const memberId = Number(uuid);
  return memberSeatKey(Number.isSafeInteger(memberId) ? memberId : null, `u${uuid}`);
}

/** The view-transition name a player wears wherever they stand: a desk row, a pool card, then a slot. */
export function playerTransitionName(seatKey: string) {
  return `mix-p-${seatKey}`;
}

/** The view-transition name a hero wears off the grid: in a ban row, or beside its player. */
export function heroTransitionName(heroId: number) {
  return `mix-h-${heroId}`;
}

/**
 * The draft's two rosters laid over the lobby's shape, in pick position order: the captain on top, every pick in the
 * slot its role takes, open slots still empty. Names are positional (`teamNames[i]`), the lineup the draft writes
 * keeps the same order.
 */
export function draftRoomTeams(board: DraftBoard, teamNames: readonly string[]): RoomTeam[] {
  const views = buildTeamViews(board);
  const shape = board.session.roster_shape;
  return [...board.teams]
    .sort((left, right) => left.draft_position - right.draft_position)
    .map((team, index) => {
      const view = views.get(team.id);
      return {
        name: teamNames[index] ?? team.name,
        averageRank: view?.avgRank ?? null,
        slots: (view?.cells ?? []).map((cell, position) => ({
          key: `${team.id}:${position}`,
          role: cell.code === OPEN_SLOT_CODE ? null : cell.code,
          seat:
            cell.player == null
              ? null
              : {
                  key: memberSeatKey(cell.player.workspace_member_id ?? null, `d${cell.player.id}`),
                  memberId: cell.player.workspace_member_id ?? null,
                  name: draftPlayerName(cell.player),
                  role: cell.role,
                  rank: slotRankForPlayer(cell.player, cell.role, shape),
                  isCaptain: cell.player.is_captain,
                  heroId: null,
                  teamMemberId: null
                }
        })),
        bans: [],
        unassignedPicks: [],
        side: null
      };
    });
}

/** The lobby's selected lineup (a balance option or the draft's result) as room teams. */
export function lineupRoomTeams(variant: PickupVariant): RoomTeam[] {
  return variant.teams.map((team, index) => ({
    name: team.name,
    averageRank: team.averageRank,
    slots: team.seats.map((seat) => {
      const memberId = Number(seat.uuid);
      const known = Number.isSafeInteger(memberId) ? memberId : null;
      return {
        key: `${index}:${seat.uuid}`,
        role: seat.role === OPEN_SLOT_CODE ? null : seat.role,
        seat: {
          key: lineupSeatKey(seat.uuid),
          memberId: known,
          name: seat.name,
          role: seat.role,
          rank: seat.rating,
          isCaptain: seat.isCaptain,
          heroId: null,
          teamMemberId: null
        }
      };
    }),
    bans: [],
    unassignedPicks: [],
    side: null
  }));
}

/**
 * The hero room laid over the teams: each team's bans in the order they landed, each player's hero and seat in the
 * room, a captain's picks not yet assigned, and the side a team starts on. A live seat is matched to a lineup team by
 * slot order; a player to the room's seat by workspace member, by name where the room does not say.
 */
export function withHeroRoom(
  teams: readonly RoomTeam[],
  state: PickBanState | null,
  liveSeats: readonly PickBanSeat[]
): RoomTeam[] {
  if (state == null) return [...teams];
  const order = [...liveSeats].sort((left, right) => left.slot - right.slot).map((seat) => seat.id);
  const teamIndex = (encounterTeamId: number | null) =>
    encounterTeamId == null ? -1 : order.indexOf(encounterTeamId);
  const members = new Map(state.members.map((member) => [member.id, member]));
  const memberByWorkspace = new Map<number, number>();
  const memberByName = new Map<string, number>();
  for (const member of state.members) {
    if (member.workspace_member_id != null) memberByWorkspace.set(member.workspace_member_id, member.id);
    else memberByName.set(member.name, member.id);
  }
  const bans: number[][] = teams.map(() => []);
  const unassigned: number[][] = teams.map(() => []);
  const heroByMember = new Map<number, number>();
  const applied = [...state.pool].sort(
    (left, right) => (left.action_index ?? 0) - (right.action_index ?? 0) || left.id - right.id
  );
  for (const entry of applied) {
    if (entry.status !== "banned" && entry.status !== "picked") continue;
    const member = entry.picked_for_member_id == null ? undefined : members.get(entry.picked_for_member_id);
    if (entry.status === "picked" && member != null) {
      heroByMember.set(member.id, entry.item_id);
      continue;
    }
    const index = teamIndex(entry.picked_by_team_id);
    if (index < 0 || index >= teams.length) continue;
    (entry.status === "banned" ? bans : unassigned)[index].push(entry.item_id);
  }
  const sides = state.starting_sides?.find((entry) => entry.position === 1)?.sides ?? {};
  return teams.map((team, index) => ({
    ...team,
    bans: bans[index],
    unassignedPicks: unassigned[index],
    side: order[index] == null ? null : (sides[String(order[index])] ?? null),
    slots: team.slots.map((slot) => {
      if (slot.seat == null) return slot;
      const teamMemberId =
        (slot.seat.memberId != null ? memberByWorkspace.get(slot.seat.memberId) : undefined) ??
        memberByName.get(slot.seat.name) ??
        null;
      return {
        ...slot,
        seat: {
          ...slot.seat,
          heroId: teamMemberId != null ? (heroByMember.get(teamMemberId) ?? null) : null,
          teamMemberId
        }
      };
    })
  }));
}

/** An available player as the captain on the clock sees them: the roles they may be picked on now, or why not. */
export interface PoolPlayer {
  player: DraftPlayer;
  /** Roles the server accepts for this pick, best rank first. Empty: not pickable for this team now. */
  roles: string[];
  /** The server's reason for refusing every role (`slot_filled`, `role_shortage`, ...); null when pickable or unknown. */
  reason: string | null;
}

/**
 * Who is still in the pool, strongest first. With the captain's pick options loaded, each player carries the roles the
 * pick may seat them on; without them (spectators, between turns) every player is listed with no verdict.
 */
export function poolPlayers(board: DraftBoard, options: DraftPickOptionsResponse | null): PoolPlayer[] {
  const current = options != null && options.pick_id === board.current_pick?.id ? options : null;
  return board.players
    .filter((player) => player.status === "available")
    .sort(
      (left, right) =>
        (right.effective_rank ?? -1) - (left.effective_rank ?? -1) || draftPlayerName(left).localeCompare(draftPlayerName(right))
    )
    .map((player) => {
      if (current == null) return { player, roles: [], reason: null };
      const mine = current.options.filter((option) => option.player_id === player.id);
      const roles = mine
        .filter((option) => option.is_safe)
        .map((option) => roleOf(option.role))
        .sort((left, right) => (player.role_ranks[right] ?? -1) - (player.role_ranks[left] ?? -1));
      const reason =
        roles.length > 0 ? null : (mine.find((option) => option.reason_code != null)?.reason_code ?? "no_slot");
      return { player, roles, reason };
    });
}
