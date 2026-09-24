/**
 * Pure derivations the draft room renders from one board snapshot.
 *
 * Everything here adapts to the session's roster SHAPE (`slots` over
 * tank/damage/support/flex): no function assumes five slots, three roles or a
 * snake. What the server decides (fit, safety, the autopick) is never
 * recomputed here — this module only arranges what the board already says.
 */

import { orderSlotCodes, type RosterShape, type RosterSlotCode } from "@/lib/roster/shape";
import type {
  DraftBoard,
  DraftPick,
  DraftPlayer,
  DraftPresenceState,
  DraftRole,
  DraftTeam,
  DraftTeamFitScore
} from "@/types/draft.types";

import type { DraftGating } from "./logic";
import {
  buildRosterByTeam,
  playerRoles,
  rosterRoleForPlayer,
  slotRankForPlayer,
  type DraftPoolRoleFilter
} from "./workspace-model";

/** Canonical role order, matching `ROSTER_SLOT_CODES` minus `flex`. */
export const DRAFT_ROLES: readonly DraftRole[] = ["tank", "damage", "support"];

// ---------------------------------------------------------------------------
// Seats and the acting team

export type DraftSeat = "captain" | "captain_admin" | "admin" | "spectator";

export function seatOf(gating: DraftGating): DraftSeat {
  if (gating.isCaptain && gating.isAdmin) return "captain_admin";
  if (gating.isCaptain) return "captain";
  if (gating.isAdmin) return "admin";
  return "spectator";
}

/** A captain-admin chooses whom a selection is for while someone else is on the clock. */
export type PickTarget = "mine" | "clock";

export function onClockTeamId(board: DraftBoard): number | null {
  return board.current_pick?.draft_team_id ?? null;
}

/**
 * The team the viewer is selecting FOR. A captain always prepares their own
 * pick (before their turn too); an admin acts for the team on the clock; a
 * captain-admin picks with `target`. `null`: nobody to act for (spectator, or
 * the draft is over).
 */
export function actingTeamId(board: DraftBoard, gating: DraftGating, target: PickTarget): number | null {
  const status = board.session.status;
  if (status === "completed" || status === "cancelled") return null;
  const clock = onClockTeamId(board);
  const mine = gating.myTeamId;
  if (!gating.isAdmin) return mine;
  if (mine == null) return clock;
  if (clock == null || clock === mine || target === "mine") return mine;
  return clock;
}

/** The player and role a seat has lined up. Kept only while the player is still available. */
export interface RoomSelection {
  playerId: number;
  role: DraftRole;
}

/** The captain's server-side queue as the pool and island edit it. `null` for anyone without a team. */
export interface QueueControls {
  /** Queue order = autopick priority; available players only. */
  ids: readonly number[];
  toggle: (playerId: number) => void;
  move: (playerId: number, direction: -1 | 1) => void;
}

/** The selection replaces a captain's pick: an admin acting for a team that is not theirs, on the clock. */
export function isOverrideAct(board: DraftBoard, gating: DraftGating, actingId: number | null): boolean {
  return gating.isAdmin && actingId != null && actingId !== gating.myTeamId && actingId === onClockTeamId(board);
}

// ---------------------------------------------------------------------------
// Rosters laid over the shape

export interface TeamSlotCell {
  /** The slot the shape defines at this position. */
  code: RosterSlotCode;
  player: DraftPlayer | null;
  /** The role the seated player plays here (their pick's role, else their primary). */
  role: DraftRole | null;
  /** Seated on a role they did not register for. */
  offRole: boolean;
}

export interface TeamView {
  team: DraftTeam;
  /** Shape order; `team_size` long (longer only if the server seated more than the shape holds). */
  cells: TeamSlotCell[];
  roster: DraftPlayer[];
  /** Open role-specific slots per role. */
  openRoles: ReadonlyMap<DraftRole, number>;
  openFlex: number;
  full: boolean;
  avgRank: number | null;
}

/**
 * Seat every rostered player into the shape's cells: their role's slot first,
 * a flex slot next. The server matches flex slots itself and never says which
 * player holds one, so this is a display arrangement, not a claim about it.
 */
export function buildTeamViews(board: DraftBoard): Map<number, TeamView> {
  const shape = board.session.roster_shape;
  const rosters = buildRosterByTeam(board.players);
  const pickNo = new Map<number, number>();
  for (const pick of board.picks) {
    if (pick.picked_player_id != null) pickNo.set(pick.picked_player_id, pick.overall_no);
  }
  const views = new Map<number, TeamView>();
  for (const team of board.teams) {
    // Captain first (seated before pick 1), then in pick order.
    const roster = [...(rosters.get(team.id) ?? [])].sort(
      (a, b) => (a.is_captain ? -1 : pickNo.get(a.id) ?? 1e9) - (b.is_captain ? -1 : pickNo.get(b.id) ?? 1e9)
    );
    const cells: TeamSlotCell[] = orderSlotCodes(shape.slots).flatMap((code) =>
      Array.from({ length: shape.slots[code] ?? 0 }, () => ({ code, player: null, role: null, offRole: false }))
    );
    for (const player of roster) {
      const role = rosterRoleForPlayer(player, board.picks);
      const registered = role != null && playerRoles(player).includes(role);
      const free = (code: RosterSlotCode) => cells.find((cell) => cell.player == null && cell.code === code);
      const target = (role != null ? free(role) : undefined) ?? free("flex") ?? cells.find((cell) => cell.player == null);
      const seat: TeamSlotCell = target ?? { code: "flex", player: null, role: null, offRole: false };
      if (!target) cells.push(seat);
      seat.player = player;
      seat.role = role;
      seat.offRole = shape.has_role_slots && role != null && (!registered || (seat.code !== "flex" && seat.code !== role));
    }
    const openRoles = new Map<DraftRole, number>();
    let openFlex = 0;
    for (const cell of cells) {
      if (cell.player != null) continue;
      if (cell.code === "flex") openFlex += 1;
      else openRoles.set(cell.code, (openRoles.get(cell.code) ?? 0) + 1);
    }
    const ranks = cells.flatMap((cell) => {
      if (cell.player == null) return [];
      const rank = slotRankForPlayer(cell.player, cell.role, shape);
      return rank == null ? [] : [rank];
    });
    views.set(team.id, {
      team,
      cells,
      roster,
      openRoles,
      openFlex,
      full: cells.every((cell) => cell.player != null),
      avgRank: ranks.length > 0 ? ranks.reduce((sum, rank) => sum + rank, 0) / ranks.length : null
    });
  }
  return views;
}

/** A role the team can still seat: an open slot of that role, or an open flex slot. */
export function canSeat(view: TeamView, role: DraftRole): boolean {
  return (view.openRoles.get(role) ?? 0) > 0 || view.openFlex > 0;
}

/** The player's roles this team can still seat, primary first. */
export function seatableRoles(player: DraftPlayer, view: TeamView): DraftRole[] {
  return playerRoles(player).filter((role) => canSeat(view, role));
}

/** Roles the team can still seat anybody on — the `need` filter's set. */
export function needRoles(view: TeamView): Set<DraftRole> {
  return new Set(DRAFT_ROLES.filter((role) => canSeat(view, role)));
}

/**
 * The role a row click selects: the role filter when it is seatable, else the
 * player's highest-ranked seatable role (primary wins ties). `null`: nothing
 * of theirs fits this team.
 */
export function bestSeatRole(
  player: DraftPlayer,
  view: TeamView,
  roleFilter: DraftPoolRoleFilter
): DraftRole | null {
  const roles = seatableRoles(player, view);
  if (roleFilter !== "all" && roleFilter !== "need" && roles.includes(roleFilter)) return roleFilter;
  let best: DraftRole | null = null;
  for (const role of roles) {
    if (best == null || (player.role_ranks[role] ?? -1) > (player.role_ranks[best] ?? -1)) best = role;
  }
  return best;
}

// ---------------------------------------------------------------------------
// Pool columns, market, demand, fit

/**
 * The role columns of the pool: every role the shape has a slot for, plus —
 * when flex slots exist — every role somebody in the pool plays, since a flex
 * slot seats any of them. An all-flex pool of damage mains shows one column.
 */
export function poolRoleColumns(shape: RosterShape, players: DraftPlayer[]): DraftRole[] {
  return DRAFT_ROLES.filter(
    (role) =>
      (shape.slots[role] ?? 0) > 0 ||
      (shape.flex_slots > 0 && players.some((player) => playerRoles(player).includes(role)))
  );
}

export interface RoleMarket {
  role: DraftRole;
  /** Role-specific open slots across every team (flex slots excluded). */
  openSlots: number;
  /** Available players whose primary role this is. */
  primary: number;
  /** Available players who play it as a secondary role. */
  secondary: number;
  /** Fewer players than slots: somebody will play off-role. */
  deficit: boolean;
  /** Fewer mains than slots. */
  tight: boolean;
}

/** Supply against demand per role slot. Empty under an all-flex shape, where no slot asks for a role. */
export function roleMarket(board: DraftBoard, views: ReadonlyMap<number, TeamView>): RoleMarket[] {
  const shape = board.session.roster_shape;
  if (!shape.has_role_slots) return [];
  const available = board.players.filter((player) => player.status === "available");
  return DRAFT_ROLES.filter((role) => (shape.slots[role] ?? 0) > 0).map((role) => {
    let openSlots = 0;
    for (const view of views.values()) openSlots += view.openRoles.get(role) ?? 0;
    const primary = available.filter((player) => player.primary_role === role).length;
    const secondary = available.filter(
      (player) => player.primary_role !== role && playerRoles(player).includes(role)
    ).length;
    return {
      role,
      openSlots,
      primary,
      secondary,
      deficit: openSlots > 0 && primary + secondary < openSlots,
      tight: openSlots > 0 && primary < openSlots
    };
  });
}

/** How many teams could still seat this player on one of their roles. */
export function demandCount(player: DraftPlayer, views: ReadonlyMap<number, TeamView>): number {
  let count = 0;
  for (const view of views.values()) if (seatableRoles(player, view).length > 0) count += 1;
  return count;
}

export interface PlayerFit {
  role: DraftRole | null;
  score: number;
}

/**
 * One fit per player out of the server's per-(player, role) scores: the
 * filtered role's score when there is one, else the player's best.
 */
export function fitByPlayer(
  scores: readonly DraftTeamFitScore[] | undefined,
  roleFilter: DraftPoolRoleFilter
): Map<number, PlayerFit> {
  const byPlayer = new Map<number, PlayerFit>();
  const pinned = roleFilter !== "all" && roleFilter !== "need" ? roleFilter : null;
  for (const entry of scores ?? []) {
    const current = byPlayer.get(entry.player_id);
    const entryPinned = pinned != null && entry.role === pinned;
    const currentPinned = pinned != null && current?.role === pinned;
    const wins =
      current == null || (entryPinned !== currentPinned ? entryPinned : entry.score > current.score);
    if (wins) byPlayer.set(entry.player_id, { role: entry.role, score: entry.score });
  }
  return byPlayer;
}

// ---------------------------------------------------------------------------
// The pick timeline

export function isResolvedPick(pick: DraftPick): boolean {
  return pick.status === "completed" || pick.status === "autopicked";
}

function byOverall(picks: readonly DraftPick[]): DraftPick[] {
  return [...picks].sort((a, b) => a.overall_no - b.overall_no);
}

/** Picks still to be made, the one on the clock first. */
export function remainingPicks(board: DraftBoard): DraftPick[] {
  return byOverall(board.picks.filter((pick) => pick.status === "on_clock" || pick.status === "upcoming"));
}

/**
 * How many picks until the team is on the clock: `0` while it is, `null` when
 * it has no pick left.
 */
export function turnsUntil(board: DraftBoard, teamId: number): number | null {
  const index = remainingPicks(board).findIndex((pick) => pick.draft_team_id === teamId);
  return index < 0 ? null : index;
}

/** The next `count` picks after the one on the clock. */
export function nextPicks(board: DraftBoard, count: number): DraftPick[] {
  const remaining = remainingPicks(board);
  const start = remaining[0]?.status === "on_clock" ? 1 : 0;
  return remaining.slice(start, start + count);
}

/** Resolved picks, newest first. */
export function pickHistory(board: DraftBoard): DraftPick[] {
  return byOverall(board.picks.filter(isResolvedPick)).reverse();
}

export function lastResolvedPick(board: DraftBoard): DraftPick | null {
  return pickHistory(board)[0] ?? null;
}

/** The round being drafted: the clock's, else the last resolved one's, else the first. */
export function currentRound(board: DraftBoard): number {
  return board.current_pick?.round_no ?? lastResolvedPick(board)?.round_no ?? 1;
}

export type RoundDirection = "forward" | "reverse" | "custom";

/**
 * Which way a round runs, read off its actual pick rows against the seat
 * order: never a snake formula, because `linear` and `custom` formats (and
 * dynamic re-seats) order rounds any way they like.
 */
export function roundDirection(board: DraftBoard, round: number): RoundDirection {
  const position = new Map(board.teams.map((team) => [team.id, team.draft_position]));
  const seats = board.picks
    .filter((pick) => pick.round_no === round)
    .sort((a, b) => a.pick_in_round - b.pick_in_round)
    .map((pick) => position.get(pick.draft_team_id) ?? 0);
  if (seats.every((seat, index) => index === 0 || seat > seats[index - 1])) return "forward";
  if (seats.every((seat, index) => index === 0 || seat < seats[index - 1])) return "reverse";
  return "custom";
}

export type PickState = "done" | "current" | "upcoming" | "skipped";

export function pickState(pick: DraftPick): PickState {
  if (isResolvedPick(pick)) return "done";
  if (pick.status === "on_clock") return "current";
  if (pick.status === "skipped") return "skipped";
  return "upcoming";
}

/** The picks of one round, in order — the clock strip's tick track. */
export function roundPicks(board: DraftBoard, round: number): DraftPick[] {
  return board.picks.filter((pick) => pick.round_no === round).sort((a, b) => a.pick_in_round - b.pick_in_round);
}

export function roundNumbers(board: DraftBoard): number[] {
  return [...new Set(board.picks.map((pick) => pick.round_no))].sort((a, b) => a - b);
}

export interface OrderRow {
  team: DraftTeam;
  /** Indexed like `roundNumbers(board)`; `null` where the team has no pick that round. */
  cells: (DraftPick | null)[];
}

/** The team × round grid of the order tab, rows in seat order. */
export function orderGrid(board: DraftBoard): OrderRow[] {
  const rounds = roundNumbers(board);
  return [...board.teams]
    .sort((a, b) => a.draft_position - b.draft_position)
    .map((team) => ({
      team,
      cells: rounds.map(
        (round) => board.picks.find((pick) => pick.draft_team_id === team.id && pick.round_no === round) ?? null
      )
    }));
}

/** Picks between the one on the clock and this one (`0`: it is on the clock); `null` once resolved. */
export function picksAway(board: DraftBoard, pick: DraftPick): number | null {
  const index = remainingPicks(board).findIndex((entry) => entry.id === pick.id);
  return index < 0 ? null : index;
}

// ---------------------------------------------------------------------------
// Teams panel filter and sort

export type TeamFilter = "all" | "follow" | DraftRole;
export type TeamSort = "order" | "next" | "avg";

export function teamsNeedingRole(views: ReadonlyMap<number, TeamView>, role: DraftRole): number {
  let count = 0;
  for (const view of views.values()) if ((view.openRoles.get(role) ?? 0) > 0) count += 1;
  return count;
}

export function filterSortTeams(
  board: DraftBoard,
  views: ReadonlyMap<number, TeamView>,
  options: { filter: TeamFilter; sort: TeamSort; followed: ReadonlySet<number>; myTeamId: number | null }
): TeamView[] {
  const { filter, sort, followed, myTeamId } = options;
  const list = [...views.values()].filter((view) => {
    if (filter === "all") return true;
    if (filter === "follow") return followed.has(view.team.id) || view.team.id === myTeamId;
    return (view.openRoles.get(filter) ?? 0) > 0;
  });
  const bySeat = (a: TeamView, b: TeamView) => a.team.draft_position - b.team.draft_position;
  if (sort === "avg") {
    return list.sort((a, b) => (b.avgRank ?? -1) - (a.avgRank ?? -1) || bySeat(a, b));
  }
  if (sort === "next") {
    const turn = (view: TeamView) => turnsUntil(board, view.team.id) ?? Number.POSITIVE_INFINITY;
    return list.sort((a, b) => turn(a) - turn(b) || bySeat(a, b));
  }
  return list.sort(bySeat);
}

// ---------------------------------------------------------------------------
// Header facts and the finished-draft summary

/** Everyone watching: signed-in connections plus anonymous ones. */
export function viewerCount(presence: DraftPresenceState): number {
  return Object.keys(presence.users).length + presence.anonymous_viewer_count;
}

export function captainsOnline(
  board: DraftBoard,
  onlineCaptainIds: ReadonlySet<number>
): { online: number; total: number } {
  const captains = board.teams.filter((team) => team.captain_auth_user_id != null);
  return {
    online: captains.filter((team) => onlineCaptainIds.has(team.captain_auth_user_id as number)).length,
    total: captains.length
  };
}

export interface DraftSummary {
  /** Strongest minus weakest team average; `null` with fewer than two averaged teams. */
  spread: number | null;
  offRole: number;
  autopicks: number;
  overrides: number;
  picks: number;
}

export function draftSummary(board: DraftBoard, views: ReadonlyMap<number, TeamView>): DraftSummary {
  const averages = [...views.values()].flatMap((view) => (view.avgRank == null ? [] : [view.avgRank]));
  let offRole = 0;
  for (const view of views.values()) offRole += view.cells.filter((cell) => cell.offRole).length;
  const resolved = board.picks.filter(isResolvedPick);
  return {
    spread: averages.length > 1 ? Math.max(...averages) - Math.min(...averages) : null,
    offRole,
    autopicks: resolved.filter((pick) => pick.is_autopick).length,
    overrides: resolved.filter((pick) => pick.is_admin_override).length,
    picks: board.picks.length
  };
}
