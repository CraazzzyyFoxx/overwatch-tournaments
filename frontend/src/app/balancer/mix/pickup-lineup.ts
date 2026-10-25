import type { DivisionGrid } from "@/types/workspace.types";
import type { DisciplineMetadata } from "@/types/discipline.types";
import { ratedDimension, registrationRoles, showsRoles, slotRank, type RoleOntology } from "@/lib/roster/ontology";
import { roleOf, toRoleRef, type RoleRef } from "@/lib/roster/role-ref";
import { OPEN_SLOT_CODE, solverSlotCode, type RosterShape } from "@/lib/roster/shape";
import {
  type CustomGame,
  type CustomGameOutcome,
  type CustomGameParticipationEntry,
  type CustomGamePlayer,
  type CustomGamePlayerPatch,
  type CustomGameSettings,
  type MixParticipation,
  type RankSource,
  type RotationRecommendation,
} from "@/services/custom-game.service";

/** What recording a match needs: the click, and whose lobby's live match it was. */
export type PickupRecordOutcomeInput = {
  outcome: CustomGameOutcome;
  lobbyIndex: number;
};

/**
 * Lineup rules for a pickup mix, kept pure so the panels stay presentational.
 *
 * Two pools exist: the workspace **player pool** (everyone the workspace knows)
 * and the mix **lineup** (who is in this mix). Membership and participation are
 * separate: `participation === "benched"` sits a player out without dropping
 * their rank override or role order, so a host can toggle a late arrival on and
 * off without rebuilding anything.
 *
 * Role vocabulary is the mix owner's game (`MixOwner`): its rated roles, in the order its ontology declares them.
 */

/** The role references a stored order writes: leaf refs of the owner's rated dimension, nothing guessed. */
export function roleRefsOf(order: readonly string[], dimension: string): RoleRef[] {
  return order.map((code) => toRoleRef(code, null, dimension));
}

/** A terminal mix is read-only server-side, so its write controls are hidden. */
export const PICKUP_TERMINAL_STATUSES: Record<string, true> = { completed: true, cancelled: true };

/**
 * Whoever passes the server's `CustomGameService._writable`: the host, a co-host or a superuser, while the mix is
 * still open (a completed or cancelled one is read-only, so its controls are hidden rather than left to 409).
 */
export function canWriteMix(game: CustomGame | undefined, userId: number | null, isSuperuser: boolean): boolean {
  if (game == null || PICKUP_TERMINAL_STATUSES[game.status]) return false;
  if (isSuperuser) return true;
  return userId != null && (game.host_user_id === userId || game.co_hosts.some((coHost) => coHost.user_id === userId));
}

/**
 * The roles the balancer may use for this row, in the order the host set them.
 *
 * A stored `null` means "not configured yet", which the backend expands to
 * every role the player has a rank for — mirror that here so the UI shows the
 * same set the balance would use. Position is the balancer's priority: the
 * first role in the array is the one the solver tries to seat the player in
 * first (see `CustomGamePlayer.roles`), so this is also the only order the UI
 * ever shows or writes. Reordering happens through an explicit drag in the
 * player sheet, never by re-deriving it from a rank — a rank fix and a
 * priority choice are two different decisions a host makes at two different
 * times, and folding one into the other means neither survives a moment the
 * host isn't actively looking at this row.
 */
export function resolveRoleOrder(row: Pick<CustomGamePlayer, "roles" | "ranks">, roles: readonly string[]): string[] {
  if (row.roles == null) {
    // Ranked roles in the game's declared order (`roles`); a rank key the dictionary does not list sorts last.
    return Object.keys(row.ranks)
      .filter((role) => row.ranks[role] != null)
      .sort((a, b) => slotRank(roles, a) - slotRank(roles, b));
  }
  // The server validated every reference against the game's roles; the host's order is kept as stored. The open
  // slot (`flex`) is a seat, never a role a player can be ordered on.
  return [...new Set(row.roles.map((ref) => roleOf(ref)).filter((code) => code !== OPEN_SLOT_CODE))];
}

/**
 * Turn one role on or off within a stored priority order.
 *
 * The order *is* the balancer's priority, so a role that turns on lands at the
 * end of it rather than being resorted — the host's existing order for the
 * other roles is left exactly as they set it.
 */
export function toggleRole(order: readonly string[], role: string): string[] {
  return order.includes(role) ? order.filter((item) => item !== role) : [...order, role];
}

export type LineupIssue = "no_role" | "no_rank";

/** A balance candidate, as the server filters them: in the lineup (not benched) and present (not away). */
function inBalance(row: Pick<CustomGamePlayer, "participation" | "away">): boolean {
  return row.participation !== "benched" && !row.away;
}

/**
 * What would make `balance` reject this row. An active player with no playable
 * ranked role fails the whole run server-side (`missing_ranked_role`), so it is
 * worth showing before the host presses Balance. A benched or away row is no
 * candidate, so it fails nothing.
 */
export function getLineupIssue(row: CustomGamePlayer, roles: readonly string[]): LineupIssue | null {
  if (!inBalance(row)) {
    return null;
  }
  const order = resolveRoleOrder(row, roles);
  if (order.length === 0) {
    return row.roles == null ? "no_rank" : "no_role";
  }
  return order.some((role) => row.ranks[role] != null) ? null : "no_rank";
}

/** One label rule shared by the lineup, the teams and the sheet. */
export function playerLabel(
  row: Pick<CustomGamePlayer, "display_name" | "identity" | "workspace_member_id">,
): string {
  return row.display_name || row.identity?.handle || `#${row.workspace_member_id}`;
}

/** Mean effective rank across the roles the player can actually be assigned. */
export function averageRank(row: Pick<CustomGamePlayer, "roles" | "ranks">, roles: readonly string[]): number | null {
  const values = resolveRoleOrder(row, roles)
    .map((role) => row.ranks[role])
    .filter((value): value is number => value != null);
  if (values.length === 0) {
    return null;
  }
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length);
}

export type LineupSummary = {
  total: number;
  active: number;
  benched: number;
  blocking: number;
};

/** `active` counts the balance candidates; an away row is neither active nor benched, but stays in `total`. */
export function summarizeLineup(rows: CustomGamePlayer[], roles: readonly string[]): LineupSummary {
  let active = 0;
  let benched = 0;
  let blocking = 0;
  for (const row of rows) {
    if (inBalance(row)) {
      active += 1;
    }
    if (row.participation === "benched") {
      benched += 1;
    }
    if (getLineupIssue(row, roles) != null) {
      blocking += 1;
    }
  }
  return { total: rows.length, active, benched, blocking };
}

/**
 * Lobbies are two teams. A mix's format fixes the seats of ONE team, so one lobby needs twice that before a balance
 * can seat everyone, and a mix running several lobbies asks for the same shape once per lobby.
 */
const TEAMS_PER_LOBBY = 2;

/**
 * The mix owner's game, as the lineup reads it: the game's roles in declared order, what one lobby asks of each role
 * (from the mix's own frozen roster shape, never a fixed table), the lobby size and the grid its ranks are on.
 * Everything is empty/`null` while the owner's metadata is still loading -- nothing is guessed in the meantime.
 */
export type MixOwner = {
  /** The owner's role dictionary: names, glyphs and tints of its roles. `null` until it loads. */
  ontology: RoleOntology | null;
  /** The game's own name, for labels that say where a rank came from. */
  gameName: string | null;
  /** The game's name when it collects a live native rank (a rank to read beside the author's), else `null`. */
  nativeRankName: string | null;
  /** The rated dimension role references are written in. `null` until metadata loads, so nothing writes a guess. */
  dimension: string | null;
  /** Roles a lineup row may play, in the game's declared order. */
  roles: readonly string[];
  /**
   * More than one role to choose between. A one-role game (Deadlock) shows no role UI: no role order, no role-supply
   * strip, no slot labels. Derived from the role count, not a flag.
   */
  showsRoles: boolean;
  /** The game has Full flex players (`discipline.flex`); `false` hides the switch and never sends one. `false` until metadata loads. */
  flex: boolean;
  /** Seats ONE lobby needs per role (`TEAMS_PER_LOBBY ×` the shape's slots); roles the format has no seat for are absent. */
  demand: Readonly<Record<string, number>>;
  /** Seats one lobby's balance can actually fill (`TEAMS_PER_LOBBY × team_size`); `null` while the shape is unknown. */
  lobbySize: number | null;
  /** The grid a mix's ranks are on: the owner game's global ladder, never the workspace's tournament grid. */
  grid: DivisionGrid;
};

/**
 * The owner view of one mix from its game's metadata and the mix's own roster shape. `workspaceGrid` is read only
 * for a game without a native ladder: there the workspace grid is the scale its ranks are entered on.
 */
export function buildMixOwner(
  metadata: DisciplineMetadata | null | undefined,
  shape: RosterShape | null | undefined,
  workspaceGrid: DivisionGrid,
): MixOwner {
  const ontology = metadata ?? null;
  const roles = registrationRoles(ontology).map((role) => role.code);
  const demand: Record<string, number> = {};
  for (const role of roles) {
    const seats = shape?.slots[role] ?? 0;
    if (seats > 0) {
      demand[role] = TEAMS_PER_LOBBY * seats;
    }
  }
  // Mix ranks live on the game's own scale in every workspace; a workspace grid (e.g. tournament divisions 1-20)
  // would read a 3500 as its top tier. Empty while metadata loads.
  const ladder = metadata?.native_ladder ?? [];
  const grid = ladder.length > 0 || metadata == null ? { tiers: [...ladder] } : workspaceGrid;
  return {
    ontology,
    gameName: metadata?.discipline.name ?? null,
    nativeRankName: metadata?.discipline.capabilities.native_rank_collection ? metadata.discipline.name : null,
    dimension: ontology ? (ratedDimension(ontology)?.code ?? null) : null,
    roles,
    showsRoles: showsRoles(ontology),
    flex: metadata?.discipline.flex ?? false,
    demand,
    lobbySize: shape ? TEAMS_PER_LOBBY * shape.team_size : null,
    grid,
  };
}

/** Where a rank came from, in the owner's words: `native` is the game's own ladder, named after the game. */
export function rankSourceLabel(
  source: RankSource,
  gameName: string | null,
  layerLabel: (source: RankSource) => string,
): string {
  return source === "native" ? (gameName ?? layerLabel("native")) : layerLabel(source);
}

export type RoleSupply = {
  role: string;
  /** Balance candidates (not benched, not away) who both selected this role and carry a rank for it. */
  supply: number;
  need: number;
  /** How many more the solver would want; 0 once the role is covered. */
  short: number;
};

/**
 * Who can actually fill each role the format asks for, counted the way the solver counts, against the demand of
 * every lobby the mix is running.
 *
 * A selected role with no rank is not supply — the balance refuses to seat it —
 * so this deliberately does not match "how many chips are lit".
 */
export function summarizeRoleSupply(rows: CustomGamePlayer[], owner: MixOwner, lobbyCount = 1): RoleSupply[] {
  // One role is no shortage to read: the lobby count already says how many are missing.
  if (!owner.showsRoles) return [];
  return owner.roles
    .filter((role) => (owner.demand[role] ?? 0) > 0)
    .map((role) => {
      const supply = rows.filter(
        (row) => inBalance(row) && resolveRoleOrder(row, owner.roles).includes(role) && row.ranks[role] != null,
      ).length;
      const need = owner.demand[role] * lobbyCount;
      return { role, supply, need, short: Math.max(0, need - supply) };
    });
}

/** Active players first, then the host's own ordering. */
export function sortLineup(rows: CustomGamePlayer[]): CustomGamePlayer[] {
  return [...rows].sort((a, b) => {
    const aBenched = a.participation === "benched";
    const bBenched = b.participation === "benched";
    if (aBenched !== bBenched) {
      return aBenched ? 1 : -1;
    }
    return a.sort_order - b.sort_order || a.id - b.id;
  });
}

/** One roster row `applyRotationHints` moves. */
export type RotationHintPatch = { workspaceMemberId: number; patch: CustomGamePlayerPatch };

/**
 * Where each actionable rotation verdict wants the row. `neutral` is absent on
 * purpose: it is "no opinion", not a column to move anybody into.
 */
const PARTICIPATION_BY_HINT: Record<"must_play" | "should_rest", MixParticipation> = {
  must_play: "must_play",
  should_rest: "benched",
};

/**
 * The moves that bring the lineup in line with the rotation-fairness read
 * (`mix_rotation.recommend_rotation`): whoever is owed a seat is pinned, and
 * whoever should rest is benched -- each exactly like the host's own drag into
 * that column. A row already in its hinted column, or with no actionable hint,
 * is left alone, so applying is idempotent. An away row is never moved: a
 * cached verdict must not bench or seat someone who stepped away.
 */
export function computeRotationHintPatches(
  rows: readonly CustomGamePlayer[],
  recommendations: readonly RotationRecommendation[],
): RotationHintPatch[] {
  const hintByMember = new Map(recommendations.map((rec) => [rec.workspace_member_id, rec]));
  const patches: RotationHintPatch[] = [];
  for (const row of rows) {
    const status = hintByMember.get(row.workspace_member_id)?.status;
    const wanted = status == null || status === "neutral" ? null : PARTICIPATION_BY_HINT[status];
    if (row.away || wanted == null || wanted === row.participation) {
      continue;
    }
    patches.push({ workspaceMemberId: row.workspace_member_id, patch: { participation: wanted } });
  }
  return patches;
}

/** The same moves as one whole-lineup write (`customGameService.setParticipation`). */
export function participationEntries(
  patches: readonly RotationHintPatch[],
): CustomGameParticipationEntry[] {
  return patches.flatMap((entry) =>
    entry.patch.participation == null
      ? []
      : [{ workspace_member_id: entry.workspaceMemberId, participation: entry.patch.participation }],
  );
}

/** One assigned seat in a balanced team, flattened out of the role buckets. */
export type PickupSeat = {
  uuid: string;
  name: string;
  /** A role code of the owner game (lower-cased), or `flex` for an open seat. */
  role: string;
  rating: number | null;
  /**
   * The host's own open rating for that bucket, when the mix balanced in
   * ranker mode -- `rating` above is then the effective one the solver used.
   * `null` in points mode, where the two cannot differ.
   */
  openRating: number | null;
  /** The solver put them off their first choice. */
  offRole: boolean;
  isFlex: boolean;
  /** Wears the team's crown: the lineup's `captain_member_id` (spec §7.2), not the solver's own flag. */
  isCaptain: boolean;
  subRole: string | null;
};

export type PickupTeam = {
  id: number;
  /** The host's override, or the caller's numbered default (`parseVariants`' `defaultName`). */
  name: string;
  averageRank: number | null;
  /** The seat uuid of the team's captain; `null` while the team has none. */
  captainUuid: string | null;
  seats: PickupSeat[];
};

type PickupVariantStats = {
  /**
   * How this option scored against its siblings, lower is better. The mix
   * engine's own total (`mix_balancer_quality_total`), or the tournament GA's
   * knee score when a mix ran on that fallback -- both rank options of the
   * same run and neither means anything across runs, so one field carries
   * whichever the solver reported.
   */
  qualityScore: number | null;
  mmrStdDev: number | null;
  ratingGap: number | null;
  /**
   * Mean rank gap per role line between the two teams -- the metric a tank
   * mismatch shows up in and the team totals hide. Rating units: the server
   * rescales it out of the solver's canonical scale.
   */
  lineGap: number | null;
  offRoleCount: number | null;
  /**
   * Off-role seats above the pool's structural floor, i.e. the ones the solver
   * could actually have avoided. `0` with a non-zero count means the roster
   * simply cannot be seated any more comfortably.
   */
  offRoleAboveMinimum: number | null;
  /** Off-role seats no split of this pool can avoid. */
  offRoleFloor: number | null;
  subRoleCollisions: number | null;
  benchedCount: number;
};

export type PickupVariant = {
  teams: PickupTeam[];
  stats: PickupVariantStats;
  benched: string[];
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * A host's team-name overrides re-keyed by the position `parseVariants` assigns
 * names by -- which is a position INSIDE one lobby. Team names are stored
 * relationally (`custom.set_team_names`) at their global index
 * (`lobby_index * 2 + team`, so A: 0-1, B: 2-3, C: 4-5 …), so each lobby's
 * overrides shift down by its own offset and every other lobby's drop out.
 */
export function teamNamesByIndex(
  settings: CustomGameSettings | undefined,
  lobbyIndex = 0,
): Record<number, string> {
  const offset = lobbyIndex * 2;
  const out: Record<number, string> = {};
  for (const [key, value] of Object.entries(settings?.team_names ?? {})) {
    const index = Number(key) - offset;
    // Two teams per lobby, the same bound `discord_lineup` reads names with:
    // without it a lobby would pick up the overrides stored for another.
    if (Number.isInteger(index) && index >= 0 && index < 2 && value.trim()) {
      out[index] = value;
    }
  }
  return out;
}

/**
 * A role-keyed player map (`ratings`, `open_ratings`, `sub_roles`) read at the seat's normalized slot code, so a
 * legacy-capitalised key (`Top`) matches its lower-case seat exactly as the bucket itself does.
 */
function slotValue(map: Record<string, unknown> | null, role: string): unknown {
  if (map == null) return undefined;
  if (role in map) return map[role];
  for (const [key, value] of Object.entries(map)) {
    if (solverSlotCode(key) === role) return value;
  }
  return undefined;
}

function parseSeats(
  roster: Record<string, unknown>,
  players: Record<string, unknown>,
  roleOrder: readonly string[],
  captainUuid: string | null,
): PickupSeat[] {
  const seats: PickupSeat[] = [];
  for (const [name, group] of Object.entries(roster)) {
    // Every bucket is a seat group: the game's roles and the open slot alike. A bucket the owner's catalog does
    // not know still keeps its players (shown as an unknown role) instead of silently dropping them.
    const role = solverSlotCode(name);
    if (role === "" || !Array.isArray(group)) {
      continue;
    }
    for (const entry of group) {
      const uuid = typeof entry === "string" || typeof entry === "number" ? String(entry) : null;
      const player = uuid == null ? null : asRecord(players[uuid]);
      if (uuid == null || player == null) {
        continue;
      }
      const preferences = Array.isArray(player.role_preferences) ? player.role_preferences : [];
      const isFlex = player.is_flex === true;
      const subRole = slotValue(asRecord(player.sub_roles), role);
      const first = typeof preferences[0] === "string" ? solverSlotCode(preferences[0]) : null;
      seats.push({
        uuid,
        name: typeof player.name === "string" ? player.name : uuid,
        role,
        // The server's `seat_rating`: the rating for the bucket they sit in, 0 without one.
        rating: asNumber(slotValue(asRecord(player.ratings), role)) ?? 0,
        // Only written by the server when the host balanced in ranker mode.
        openRating: asNumber(slotValue(asRecord(player.open_ratings), role)),
        // A flex player is never off-role: any seat is their first choice -- and an open seat names no role.
        offRole: !isFlex && role !== OPEN_SLOT_CODE && first != null && first !== role,
        isFlex,
        isCaptain: uuid === captainUuid,
        subRole: typeof subRole === "string" ? subRole : null,
      });
    }
  }
  // The game's declared role order, so the same team reads the same way every render.
  return seats.sort((a, b) => slotRank(roleOrder, a.role) - slotRank(roleOrder, b.role));
}

/**
 * Every balance option the solver returned, richest-first as it stored them.
 *
 * The mix carries the solver's lobby document (`lobby_document` server-side):
 * each player once under `players`, and each option only as role buckets of
 * player uuids plus its own numbers -- the seats are rebuilt against that map
 * here. An unrecognised shape yields an empty list rather than throwing, so a
 * malformed result degrades to "no teams to show" instead of blanking the screen.
 *
 * `roleOrder` is the owner game's declared slot order (`slotCodeOrder`); it only orders seats inside a team.
 * `defaultName` names a team the host has not renamed, by its 0-based position.
 */
export function parseVariants(
  resultJson: unknown,
  teamNames: Record<number, string>,
  roleOrder: readonly string[],
  defaultName: (index: number) => string,
): PickupVariant[] {
  const root = asRecord(resultJson);
  if (root == null || !Array.isArray(root.variants)) {
    return [];
  }
  const players = asRecord(root.players) ?? {};
  // One pool, one floor: the server hoists it out of the per-option numbers.
  const offRoleFloor = asNumber(asRecord(root.feasibility)?.structural_min_off_role);
  const out: PickupVariant[] = [];
  for (const payload of root.variants) {
    const variant = asRecord(payload);
    const teams = variant == null ? null : variant.teams;
    if (!Array.isArray(teams)) {
      continue;
    }
    const statistics = asRecord(variant?.statistics) ?? {};
    const benched = Array.isArray(variant?.benched) ? variant.benched : [];
    out.push({
      teams: teams
        .flatMap((entry) => {
          const team = asRecord(entry);
          const roster = asRecord(team?.roster);
          if (team == null || roster == null) {
            return [];
          }
          const captain = asNumber(team.captain_member_id);
          const captainUuid = captain == null ? null : String(captain);
          return [
            {
              id: asNumber(team.id),
              averageRank: asNumber(team.average_mmr),
              captainUuid,
              seats: parseSeats(roster, players, roleOrder, captainUuid),
            },
          ];
        })
        // Named by final render position, not the raw payload index: a
        // malformed entry dropped above must not shift every name after it.
        .map((team, index) => ({
          ...team,
          id: team.id ?? index + 1,
          name: teamNames[index] ?? defaultName(index),
        })),
      stats: {
        // Whichever engine ran: `mix_balancer` scores a seating with its own
        // four-term total, the tournament GA (the fallback where the native
        // engine is unavailable) with a normalised knee score. Both are
        // cleared server-side once a host hand-swaps a seat, so a missing
        // value here means "no longer the solver's arrangement", not "zero".
        qualityScore:
          asNumber(statistics.mix_balancer_quality_total) ?? asNumber(statistics.composite_score),
        mmrStdDev: asNumber(statistics.mmr_std_dev),
        ratingGap: asNumber(statistics.max_total_rating_gap),
        lineGap: asNumber(statistics.mix_balancer_role_fairness),
        offRoleCount: asNumber(statistics.off_role_count),
        offRoleAboveMinimum: asNumber(statistics.off_role_above_minimum),
        offRoleFloor,
        subRoleCollisions: asNumber(statistics.sub_role_collision_count),
        benchedCount: benched.length,
      },
      benched: benched.flatMap((entry) => {
        const name = asRecord(players[String(entry)])?.name;
        return typeof name === "string" ? [name] : [];
      }),
    });
  }
  return out;
}

/**
 * How many players one lobby's next balance can seat: in the lineup (not benched), present (not away), not on another
 * lobby's floor and not pinned to another lobby -- the server's `_lobby_candidates`, read off the board.
 */
export function lobbyCandidateCount(rows: readonly CustomGamePlayer[], lobbyIndex: number): number {
  return rows.filter(
    (row) =>
      inBalance(row) &&
      (row.current_lobby == null || row.current_lobby === lobbyIndex) &&
      (row.lobby_pin == null || row.lobby_pin === lobbyIndex),
  ).length;
}

/**
 * A waiting player's place in line, 1-based, or `null` when no seat is being waited for: the present lineup players
 * no lobby seats, ordered the way rotation owes seats (`mix_rotation.recommend_rotation`) -- the host's must-play pin
 * first, then the longest sit-out, the shortest playing streak, the fewest games and the host's own order.
 */
export function waitingQueuePosition(
  rows: readonly CustomGamePlayer[],
  rotation: readonly RotationRecommendation[],
  memberId: number,
): number | null {
  const hints = new Map(rotation.map((rec) => [rec.workspace_member_id, rec]));
  const waiting = rows
    .filter((row) => row.participation !== "benched" && !row.away && row.current_lobby == null)
    .sort((a, b) => {
      const first = hints.get(a.workspace_member_id);
      const second = hints.get(b.workspace_member_id);
      return (
        Number(b.participation === "must_play") - Number(a.participation === "must_play") ||
        (second?.consecutive_sat ?? 0) - (first?.consecutive_sat ?? 0) ||
        (first?.consecutive_played ?? 0) - (second?.consecutive_played ?? 0) ||
        (first?.games_played ?? 0) - (second?.games_played ?? 0) ||
        a.sort_order - b.sort_order ||
        a.id - b.id
      );
    });
  const index = waiting.findIndex((row) => row.workspace_member_id === memberId);
  return index < 0 ? null : index + 1;
}

/** A player's own team as the phone view shows it (spec §7.5, G1). */
export type MySeatTeam = {
  lobbyIndex: number;
  teamName: string;
  nextMapId: number | null;
  /** That lobby's in-game join code, or `null` while the host set none. */
  lobbyCode: string | null;
  /** In seat order; `role` is the slot the option seats them on (the roster line's glyph). */
  members: { uuid: string; name: string; role: string; isCaptain: boolean; isMe: boolean }[];
};

/** The team the lobby's shown option seats this member in, or `null` while no lobby seats them. */
export function myLobbyTeam(
  game: CustomGame | undefined,
  memberId: number | null,
  roleOrder: readonly string[],
  defaultName: (index: number) => string,
): MySeatTeam | null {
  if (game == null || memberId == null) return null;
  const me = String(memberId);
  for (const lobby of game.lobbies) {
    const variant = parseVariants(
      lobby.balance_result,
      teamNamesByIndex(game.settings, lobby.lobby_index),
      roleOrder,
      defaultName,
    )[lobby.selected_variant_index];
    const team = variant?.teams.find((candidate) => candidate.seats.some((seat) => seat.uuid === me));
    if (team != null) {
      return {
        lobbyIndex: lobby.lobby_index,
        teamName: team.name,
        nextMapId: lobby.next_map_id,
        lobbyCode: lobby.lobby_code,
        members: team.seats.map((seat) => ({
          uuid: seat.uuid,
          name: seat.name,
          role: seat.role,
          isCaptain: seat.isCaptain,
          isMe: seat.uuid === me,
        })),
      };
    }
  }
  return null;
}
