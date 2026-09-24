import type { RosterShape } from "@/lib/roster/shape";
import type {
  DraftPick,
  DraftPickOption,
  DraftPickOptionsResponse,
  DraftPlayer,
  DraftRole
} from "@/types/draft.types";

/** `need`: players the ACTING team can still seat on at least one of their roles. */
export type DraftPoolRoleFilter = DraftRole | "all" | "need";
export type DraftPoolSort = "rank" | "name";
/** Below the wide breakpoint the room is two tabs; the teams panel holds queue and order itself. */
export const DRAFT_MOBILE_VIEWS = ["pool", "teams"] as const;
export type DraftMobileView = (typeof DRAFT_MOBILE_VIEWS)[number];
/** Which list of the board the pool panel is showing. `shortlist` is the captain's server-side queue. */
export const DRAFT_POOL_TABS = ["available", "shortlist", "all"] as const;
export type DraftPoolTab = (typeof DRAFT_POOL_TABS)[number];
export const DRAFT_TEAMS_TABS = ["rosters", "queue", "order"] as const;
export type DraftTeamsTab = (typeof DRAFT_TEAMS_TABS)[number];

export interface DraftViewParams {
  role: DraftPoolRoleFilter;
  sort: DraftPoolSort;
  view: DraftMobileView;
  pool: DraftPoolTab;
  teams: DraftTeamsTab;
  query: string;
}

export function parseDraftViewParams(params: URLSearchParams): DraftViewParams {
  const roleValue = params.get("role");
  const poolValue = params.get("pool");
  const teamsValue = params.get("teams");
  return {
    role:
      roleValue === "tank" || roleValue === "damage" || roleValue === "support" || roleValue === "need"
        ? roleValue
        : "all",
    sort: params.get("sort") === "name" ? "name" : "rank",
    view: params.get("view") === "teams" ? "teams" : "pool",
    pool: poolValue === "shortlist" || poolValue === "all" ? poolValue : "available",
    teams: teamsValue === "queue" || teamsValue === "order" ? teamsValue : "rosters",
    query: params.get("q")?.trim() ?? ""
  };
}

const ROLE_LABELS: Record<DraftRole, string[]> = {
  tank: ["tank"],
  damage: ["damage"],
  support: ["support", "sup", "heal"],
};

/**
 * `needRoles` answers the `need` filter: the roles the acting team can still
 * seat. Without an acting team (a spectator) `need` narrows nothing.
 */
export function filterDraftPlayers(
  players: DraftPlayer[],
  filters: Pick<DraftViewParams, "role" | "sort" | "query">,
  needRoles: ReadonlySet<DraftRole> | null = null,
  { sorted = true }: { sorted?: boolean } = {}
): DraftPlayer[] {
  const query = filters.query.toLocaleLowerCase();
  const matches = players.filter((player) => {
    const roles = playerRoles(player);
    const haystack = [
      player.battle_tag ?? `#${player.id}`,
      player.sub_role ?? "",
      ...Object.values(player.role_sub_roles ?? {}),
      ...roles.flatMap((r) => ROLE_LABELS[r] ?? [r]),
    ].join(" ").toLocaleLowerCase();
    const roleOk =
      filters.role === "all" ||
      (filters.role === "need"
        ? needRoles == null || roles.some((role) => needRoles.has(role))
        : roles.includes(filters.role));
    return roleOk && (!query || haystack.includes(query));
  });
  if (!sorted) return matches;
  const role = filters.role;
  return matches.sort((left, right) => {
    if (filters.sort === "name") {
      return (left.battle_tag ?? "").localeCompare(right.battle_tag ?? "");
    }
    // Filtered to one role, the rank ON that role is the one being compared.
    const rankOf = (player: DraftPlayer) =>
      (role !== "all" && role !== "need" ? player.role_ranks?.[role] : undefined) ?? player.effective_rank ?? -1;
    return rankOf(right) - rankOf(left) || left.id - right.id;
  });
}

export interface DraftPoolView {
  /** Still pickable, unfiltered — the denominator every role count is about. */
  available: DraftPlayer[];
  /** Everyone still in the draft: available and already rostered (removed players excluded). */
  all: DraftPlayer[];
  /** The captain's queue, in queue order, narrowed to players still available. */
  shortlist: DraftPlayer[];
  /** Whichever of the three `pool` names, with role/query applied; sorted except the queue. */
  filtered: DraftPlayer[];
  roleCounts: Record<DraftRole, number>;
  /** Available players the acting team can seat; `null` without an acting team. */
  needCount: number | null;
}

const NO_QUEUE: readonly number[] = [];

/**
 * The three lists the pool panel can show, plus the filtered one it renders.
 *
 * `roleCounts` deliberately stays on AVAILABLE whichever tab is open: "who is
 * left per role" is the question the role chips answer. The queue keeps its
 * own order — it IS the autopick priority, so re-sorting it would lie.
 */
export function draftPoolView(
  players: DraftPlayer[],
  filters: Pick<DraftViewParams, "role" | "sort" | "query" | "pool">,
  queueIds: readonly number[] = NO_QUEUE,
  needRoles: ReadonlySet<DraftRole> | null = null
): DraftPoolView {
  const available = players.filter((player) => player.status === "available");
  const all = players.filter((player) => player.status !== "removed");
  const byId = new Map(available.map((player) => [player.id, player]));
  const shortlist = queueIds.flatMap((id) => byId.get(id) ?? []);
  const roleCounts: Record<DraftRole, number> = { tank: 0, damage: 0, support: 0 };
  for (const player of available) {
    for (const role of playerRoles(player)) {
      roleCounts[role] += 1;
    }
  }
  const needCount =
    needRoles == null
      ? null
      : available.filter((player) => playerRoles(player).some((role) => needRoles.has(role))).length;
  const source = filters.pool === "all" ? all : filters.pool === "shortlist" ? shortlist : available;
  const filtered = filterDraftPlayers(source, filters, needRoles, { sorted: filters.pool !== "shortlist" });
  return { available, all, shortlist, filtered, roleCounts, needCount };
}

export function optionForSelection(
  response: DraftPickOptionsResponse | null,
  playerId: number,
  role: DraftRole
): DraftPickOption | null {
  return (
    response?.options.find((option) => option.player_id === playerId && option.role === role) ?? null
  );
}

/**
 * The roles this player may be picked on, primary first.
 *
 * Exactly what the server will accept: `resolve_pick_slot` validates a pick
 * through `PlayerRoster.covers(role)`, i.e. the role must be one the player has
 * a rank on (`playable`). `is_flex` is NOT consulted there, so it must not
 * widen the offer here either — a flex player's roles are whatever landed in
 * `primary_role` + `secondary_roles`, which the server derives from the same
 * playable set (all three when all three are ranked).
 */
export function playerRoles(player: DraftPlayer): DraftRole[] {
  // `primary_role` is null once the player has no playable role left; nothing
  // may be substituted for it.
  const declared = player.secondary_roles as DraftRole[];
  return Array.from(
    new Set<DraftRole>(player.primary_role ? [player.primary_role, ...declared] : declared)
  );
}

export function buildRosterByTeam(players: DraftPlayer[]): Map<number, DraftPlayer[]> {
  const rosters = new Map<number, DraftPlayer[]>();
  for (const player of players) {
    if (player.drafted_by_team_id == null || player.status === "available") continue;
    const roster = rosters.get(player.drafted_by_team_id) ?? [];
    roster.push(player);
    rosters.set(player.drafted_by_team_id, roster);
  }
  return rosters;
}

export function normalizeTopHeroes(
  entries: DraftPlayer["role_top_heroes"][string] | undefined
): { slug: string; imagePath: string | null }[] {
  if (!entries) return [];
  return entries.map((e) =>
    typeof e === "string" ? { slug: e, imagePath: null } : { slug: e.slug, imagePath: e.image_path ?? null }
  );
}

export function roleTopHeroes(player: DraftPlayer, role: DraftRole) {
  return normalizeTopHeroes(player.role_top_heroes?.[role]);
}

/** Deduped hero list for a player across every role bucket in `role_top_heroes`. */
export function allPlayerHeroes(player: DraftPlayer): { slug: string; imagePath: string | null }[] {
  const seen = new Map<string, string | null>();
  for (const heroes of Object.values(player.role_top_heroes ?? {})) {
    for (const hero of normalizeTopHeroes(heroes)) {
      if (!seen.has(hero.slug)) seen.set(hero.slug, hero.imagePath);
    }
  }
  return [...seen].map(([slug, imagePath]) => ({ slug, imagePath }));
}

export function rosterRoleForPlayer(player: DraftPlayer, picks: DraftPick[]): DraftRole | null {
  const pick = picks.find((p) => p.picked_player_id === player.id && p.target_role != null);
  return (pick?.target_role as DraftRole | undefined) ?? player.primary_role;
}

/**
 * The rank that represents a player on their slot, mirroring the server's
 * `domain.draft.ranks.slot_rank`. Role slots keep it role-specific; `role=null`
 * (pool card / unseated) uses the server's best playable rank (`effective_rank`)
 * when any role rank remains. A role-less (all-flex) shape values everyone
 * that way. The flex rule itself is never recomputed here.
 */
export function slotRankForPlayer(
  player: DraftPlayer,
  role: DraftRole | null,
  shape: Pick<RosterShape, "has_role_slots">
): number | null {
  if (!shape.has_role_slots) return player.effective_rank ?? null;
  if (role == null) {
    return Object.keys(player.role_ranks ?? {}).length > 0 ? (player.effective_rank ?? null) : null;
  }
  return player.role_ranks?.[role] ?? null;
}
