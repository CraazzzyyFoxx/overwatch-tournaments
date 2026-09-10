import type { RosterShape } from "@/lib/roster-shape";
import type {
  DraftPick,
  DraftPickOption,
  DraftPickOptionsResponse,
  DraftPlayer,
  DraftRole
} from "@/types/draft.types";

export type DraftPoolRoleFilter = DraftRole | "all";
export type DraftPoolSort = "rank" | "name";
export type DraftMobileView = "pool" | "team" | "order";

export interface DraftViewParams {
  role: DraftPoolRoleFilter;
  sort: DraftPoolSort;
  view: DraftMobileView;
  query: string;
}

export function parseDraftViewParams(params: URLSearchParams): DraftViewParams {
  const roleValue = params.get("role");
  const sortValue = params.get("sort");
  const viewValue = params.get("view");
  return {
    role:
      roleValue === "tank" || roleValue === "dps" || roleValue === "support"
        ? roleValue
        : "all",
    sort: sortValue === "name" ? "name" : "rank",
    view: viewValue === "team" || viewValue === "order" ? viewValue : "pool",
    query: params.get("q")?.trim() ?? ""
  };
}

const ROLE_LABELS: Record<DraftRole, string[]> = {
  tank: ["tank"],
  dps: ["dps", "damage"],
  support: ["support", "sup", "heal"],
};

export function filterDraftPlayers(
  players: DraftPlayer[],
  filters: Pick<DraftViewParams, "role" | "sort" | "query">
): DraftPlayer[] {
  const query = filters.query.toLocaleLowerCase();
  return players
    .filter((player) => {
      const roles = playerRoles(player);
      const haystack = [
        player.battle_tag ?? `#${player.id}`,
        player.sub_role ?? "",
        ...roles.flatMap((r) => ROLE_LABELS[r] ?? [r]),
      ].join(" ").toLocaleLowerCase();
      return (filters.role === "all" || roles.includes(filters.role)) && (!query || haystack.includes(query));
    })
    .sort((left, right) => {
      if (filters.sort === "name") {
        return (left.battle_tag ?? "").localeCompare(right.battle_tag ?? "");
      }
      return (right.effective_rank ?? -1) - (left.effective_rank ?? -1) || left.id - right.id;
    });
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

/**
 * The role to preselect for a player: the first SAFE one in the player's own
 * order (primary, then the declared secondaries).
 *
 * The server emits an option per role in its own canonical order — tank, dps,
 * support (`evaluate_pick_options` iterates `HERO_TYPE_CLASSES`) — so reading
 * its first safe option handed a support main their tank option. `null` means
 * the player has no safe role at all, which is what blocks the row.
 */
export function safeRoleForPlayer(
  options: DraftPickOptionsResponse | null,
  player: DraftPlayer
): DraftRole | null {
  const safe = (options?.options ?? []).filter(
    (option) => option.player_id === player.id && option.is_safe
  );
  if (safe.length === 0) return null;
  return playerRoles(player).find((role) => safe.some((option) => option.role === role)) ?? safe[0].role;
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

export interface DraftRoundGroup {
  round: number;
  picks: DraftPick[];
}

export function groupPicksByRound(picks: DraftPick[]): DraftRoundGroup[] {
  const byRound = new Map<number, DraftPick[]>();
  for (const pick of picks) {
    const list = byRound.get(pick.round_no) ?? [];
    list.push(pick);
    byRound.set(pick.round_no, list);
  }
  return [...byRound.entries()]
    .sort(([a], [b]) => a - b)
    .map(([round, list]) => ({
      round,
      picks: [...list].sort((l, r) => l.pick_in_round - r.pick_in_round || l.overall_no - r.overall_no),
    }));
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

/**
 * How many picks a team still has to wait before it is on the clock, or `null`
 * when it is already on the clock or has no pick left. Shared by the spectator
 * board and the captain command bar so both count the same way.
 */
export function picksUntilTeamTurn(picks: DraftPick[], teamId: number): number | null {
  const upcoming = picks
    .filter((pick) => pick.status === "upcoming" || pick.status === "on_clock")
    .sort((left, right) => left.overall_no - right.overall_no);
  const index = upcoming.findIndex((pick) => pick.draft_team_id === teamId);
  return index > 0 ? index : null;
}
