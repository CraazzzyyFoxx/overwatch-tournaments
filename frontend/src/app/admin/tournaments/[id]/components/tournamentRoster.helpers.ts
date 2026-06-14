import type { Team, Player } from "@/types/team.types";

export type PlayerRoleOption = "Tank" | "Damage" | "Support";

export type TeamRosterDraftPlayer = {
  draft_id: string;
  player_id: number | null;
  state: "existing" | "new";
  name: string;
  user_id: number;
  user_name: string;
  role: PlayerRoleOption;
  sub_role: string;
  rank: number;
  is_newcomer: boolean;
  is_newcomer_role: boolean;
  is_substitution: boolean;
  related_player_id: number | null;
  related_draft_id: string | null;
};

export type TeamRosterDraftTreeNode = {
  player: TeamRosterDraftPlayer;
  children: TeamRosterDraftTreeNode[];
};

export function normalizePlayerRole(role: string | null | undefined): PlayerRoleOption {
  const normalized = role?.trim().toLowerCase();

  if (normalized === "tank") {
    return "Tank";
  }

  if (normalized === "support") {
    return "Support";
  }

  return "Damage";
}

export function createExistingRosterDraftPlayer(player: Player): TeamRosterDraftPlayer {
  return {
    draft_id: `existing:${player.id}`,
    player_id: player.id,
    state: "existing",
    name: player.name,
    user_id: player.user_id,
    user_name: player.user?.name ?? `User #${player.user_id}`,
    role: normalizePlayerRole(player.role),
    sub_role: player.sub_role ?? "",
    rank: player.rank,
    is_newcomer: player.is_newcomer,
    is_newcomer_role: player.is_newcomer_role,
    is_substitution: player.is_substitution,
    related_player_id: player.related_player_id,
    related_draft_id: null,
  };
}

export function createRosterDraftFromTeam(team: Team): TeamRosterDraftPlayer[] {
  const drafts = (team.players ?? []).map(createExistingRosterDraftPlayer);
  const draftByPlayerId = new Map(
    drafts
      .filter((draft) => draft.player_id != null)
      .map((draft) => [draft.player_id as number, draft.draft_id])
  );

  return drafts.map((draft) => ({
    ...draft,
    related_draft_id:
      draft.related_player_id != null ? (draftByPlayerId.get(draft.related_player_id) ?? null) : null,
  }));
}

export function createEmptyRosterDraftPlayer(input: {
  draftId: string;
  isSubstitution?: boolean;
  relatedDraftId?: string | null;
  relatedPlayerId?: number | null;
}): TeamRosterDraftPlayer {
  return {
    draft_id: input.draftId,
    player_id: null,
    state: "new",
    name: "",
    user_id: 0,
    user_name: "",
    role: "Damage",
    sub_role: "",
    rank: 0,
    is_newcomer: false,
    is_newcomer_role: false,
    is_substitution: input.isSubstitution ?? false,
    related_player_id: input.relatedPlayerId ?? null,
    related_draft_id: input.relatedDraftId ?? null,
  };
}

function getRolePriority(role: PlayerRoleOption): number {
  if (role === "Tank") return 1;
  if (role === "Damage") return 2;
  if (role === "Support") return 3;
  return 4;
}

export function sortRosterDraftPlayers(players: TeamRosterDraftPlayer[]): TeamRosterDraftPlayer[] {
  const draftById = new Map(players.map((player) => [player.draft_id, player]));
  const children = new Map<string, TeamRosterDraftPlayer[]>();
  const roots: TeamRosterDraftPlayer[] = [];

  for (const player of players) {
    const relatedDraftId = player.related_draft_id;
    if (player.is_substitution && relatedDraftId && draftById.has(relatedDraftId)) {
      const entries = children.get(relatedDraftId) ?? [];
      entries.push(player);
      children.set(relatedDraftId, entries);
      continue;
    }
    roots.push(player);
  }

  for (const entries of children.values()) {
    entries.sort((left, right) => right.rank - left.rank);
  }

  roots.sort((left, right) => {
    const roleDelta = getRolePriority(left.role) - getRolePriority(right.role);
    if (roleDelta !== 0) {
      return roleDelta;
    }
    return right.rank - left.rank;
  });

  const flatten = (player: TeamRosterDraftPlayer): TeamRosterDraftPlayer[] => {
    const descendants = children.get(player.draft_id) ?? [];
    return [player, ...descendants.flatMap(flatten)];
  };

  return roots.flatMap(flatten);
}

export function buildRosterDraftTree(players: TeamRosterDraftPlayer[]): TeamRosterDraftTreeNode[] {
  const orderedPlayers = sortRosterDraftPlayers(players);
  const nodeByDraftId = new Map<string, TeamRosterDraftTreeNode>(
    orderedPlayers.map((player) => [player.draft_id, { player, children: [] }])
  );
  const roots: TeamRosterDraftTreeNode[] = [];

  for (const player of orderedPlayers) {
    const node = nodeByDraftId.get(player.draft_id);
    if (!node) {
      continue;
    }
    const parent = player.related_draft_id ? nodeByDraftId.get(player.related_draft_id) : null;
    if (player.is_substitution && parent) {
      parent.children.push(node);
      continue;
    }
    roots.push(node);
  }

  return roots;
}

export function collectRosterDraftSubtreeIds(
  players: TeamRosterDraftPlayer[],
  draftId: string
): string[] {
  const childMap = new Map<string, string[]>();

  for (const player of players) {
    if (!player.related_draft_id) {
      continue;
    }
    const entries = childMap.get(player.related_draft_id) ?? [];
    entries.push(player.draft_id);
    childMap.set(player.related_draft_id, entries);
  }

  const collected: string[] = [];
  const visit = (currentDraftId: string) => {
    collected.push(currentDraftId);
    const childIds = childMap.get(currentDraftId) ?? [];
    for (const childId of childIds) {
      visit(childId);
    }
  };

  visit(draftId);
  return collected;
}

export function removeRosterDraftPlayer(
  players: TeamRosterDraftPlayer[],
  draftId: string
): {
  players: TeamRosterDraftPlayer[];
  deletedExistingPlayerId: number | null;
} {
  const subtreeIds = new Set(collectRosterDraftSubtreeIds(players, draftId));
  const deletedPlayer = players.find((player) => player.draft_id === draftId) ?? null;

  return {
    players: players.filter((player) => !subtreeIds.has(player.draft_id)),
    deletedExistingPlayerId: deletedPlayer?.player_id ?? null,
  };
}

export function buildCaptainOptions(players: TeamRosterDraftPlayer[]): Array<{
  user_id: number;
  label: string;
}> {
  const unique = new Map<number, string>();

  for (const player of sortRosterDraftPlayers(players)) {
    if (player.user_id <= 0 || unique.has(player.user_id)) {
      continue;
    }
    unique.set(player.user_id, player.user_name || player.name || `User #${player.user_id}`);
  }

  return Array.from(unique.entries()).map(([user_id, label]) => ({ user_id, label }));
}

export function buildRosterInitialSnapshot(team: Team | null) {
  return {
    team: team
      ? {
          name: team.name,
          captain_id: team.captain_id,
          avg_sr: team.avg_sr,
          total_sr: team.total_sr,
        }
      : {
          name: "",
          captain_id: 0,
          avg_sr: 0,
          total_sr: 0,
        },
    roster: team ? createRosterDraftFromTeam(team) : [],
  };
}
