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

export function filterDraftPlayers(
  players: DraftPlayer[],
  filters: Pick<DraftViewParams, "role" | "sort" | "query">
): DraftPlayer[] {
  const query = filters.query.toLocaleLowerCase();
  return players
    .filter((player) => {
      const roles = new Set<DraftRole>([
        player.primary_role,
        ...((player.secondary_roles_json ?? []) as DraftRole[])
      ]);
      const name = player.battle_tag ?? `#${player.id}`;
      return (
        (filters.role === "all" || roles.has(filters.role)) &&
        (!query || name.toLocaleLowerCase().includes(query))
      );
    })
    .sort((left, right) => {
      if (filters.sort === "name") {
        return (left.battle_tag ?? "").localeCompare(right.battle_tag ?? "");
      }
      return (right.rank_value ?? -1) - (left.rank_value ?? -1) || left.id - right.id;
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

export function playerRoles(player: DraftPlayer): DraftRole[] {
  return Array.from(
    new Set<DraftRole>([
      player.primary_role,
      ...((player.secondary_roles_json ?? []) as DraftRole[])
    ])
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

export interface DraftEventFeedItem {
  pickId: number;
  overallNo: number;
  teamName: string;
  playerName: string;
  role: DraftRole | null;
  autopick: boolean;
}

export function buildDraftEventFeed(
  picks: DraftPick[],
  teamNames: ReadonlyMap<number, string>,
  playerNames: ReadonlyMap<number, string>
): DraftEventFeedItem[] {
  return picks
    .filter(
      (pick) =>
        (pick.status === "completed" || pick.status === "autopicked") &&
        pick.picked_player_id != null
    )
    .sort((left, right) => right.overall_no - left.overall_no)
    .map((pick) => ({
      pickId: pick.id,
      overallNo: pick.overall_no,
      teamName: teamNames.get(pick.draft_team_id) ?? `#${pick.draft_team_id}`,
      playerName: playerNames.get(pick.picked_player_id!) ?? `#${pick.picked_player_id}`,
      role: pick.target_role,
      autopick: pick.is_autopick
    }));
}
