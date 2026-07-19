import { Player } from "@/types/team.types";
import { Hero } from "@/types/hero.types";
import { User, UserProfile } from "@/types/user.types";

/**
 * Fields `sortTeamPlayers` actually reads. Display-only roster fields
 * (`heroes`, `avg_mvp`, …) are intentionally excluded so callers whose row
 * type reuses the `heroes` name for a different shape (e.g. `PlayerWithStats`
 * with `heroes: Record<number, Hero[]>`) still satisfy the sort constraint.
 */
export interface SortableRosterPlayer {
  id: number;
  role: string | null;
  rank: number;
  is_substitution: boolean;
  related_player_id: number | null;
  relative_player?: number | null;
}

/** Minimal shape required for `sortTeamPlayers` / TournamentTeamTable rendering. */
export interface TeamRosterPlayer extends SortableRosterPlayer {
  name: string;
  sub_role: string | null;
  division: number;
  is_newcomer: boolean;
  is_newcomer_role: boolean;
  /** Owning user id — set on user-scoped rosters so a table can flag "you". */
  user_id?: number;
  /** Average MVP placement across the player's matches (1 = MVP/best). */
  avg_mvp?: number | null;
  /** Player's top signature heroes (same shape as per-match `heroes`). */
  heroes?: Hero[];
}

type PlayerRoleInfo = {
  role: string | null;
  sub_role?: string | null;
};

const SUB_ROLE_LABELS: Record<string, string> = {
  hitscan: "Hitscan",
  projectile: "Projectile",
  main_heal: "Main Heal",
  light_heal: "Light Heal"
};

export const formatSubRoleLabel = (subRole: string | null | undefined) => {
  if (!subRole) {
    return null;
  }

  return (
    SUB_ROLE_LABELS[subRole] ??
    subRole
      .split(/[_-]+/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ")
  );
};

export const getPlayerType = (player: PlayerRoleInfo) => {
  const subRoleLabel = formatSubRoleLabel(player.sub_role);
  if (subRoleLabel) {
    return subRoleLabel;
  }
  return "ㅤ";
};

export const sortTeamPlayers = <P extends SortableRosterPlayer>(players: P[]): P[] => {
  const getRolePriority = (role: string | null) => {
    if (role === "Tank") return 1;
    if (role === "Damage") return 2;
    if (role === "Support") return 3;
    return 4;
  };

  const playerById = new Map(players.map((p) => [p.id, p]));

  // Build substitution graph: parent -> children (who replaced them)
  const children = new Map<number, P[]>();
  const roots: P[] = [];

  for (const player of players) {
    const relatedPlayerId = player.related_player_id ?? player.relative_player ?? null;
    if (player.is_substitution && relatedPlayerId !== null && playerById.has(relatedPlayerId)) {
      const list = children.get(relatedPlayerId) ?? [];
      list.push(player);
      children.set(relatedPlayerId, list);
    } else {
      roots.push(player);
    }
  }

  // Sort children at each node by rank descending
  for (const list of children.values()) {
    list.sort((a, b) => b.rank - a.rank);
  }

  // DFS: flatten each substitution chain (player, then their replacements)
  const flatten = (player: P): P[] => {
    const result = [player];
    const subs = children.get(player.id);
    if (subs) {
      for (const sub of subs) {
        result.push(...flatten(sub));
      }
    }
    return result;
  };

  // Sort roots by role priority, then by rank within same role
  roots.sort((a, b) => {
    const rp = getRolePriority(a.role) - getRolePriority(b.role);
    if (rp !== 0) return rp;
    return b.rank - a.rank;
  });

  // Flatten: each root followed by its substitution chain
  return roots.flatMap(flatten);
};

export const getPlayerImage = (profile: UserProfile, user: User) => {
  // A user-uploaded avatar takes precedence over the derived hero art.
  if (user.avatar_url) {
    return user.avatar_url;
  }
  if (profile.most_played_hero === null) {
    return `/avatar/${user.id % 10}.png`;
  }
  return `/avatar/${profile.most_played_hero.slug}.jpg`;
};

export const getPlayerSlug = (battleTag: string | null | undefined) => {
  if (!battleTag) {
    return "";
  }
  return battleTag.replace("#", "-");
};

/** Reverse of getPlayerSlug: converts a URL slug back to the stored player name.
 *  "CraazzzyyFox-2130" → "CraazzzyyFox#2130"
 *  Names without a numeric suffix are returned unchanged.
 */
export const decodePlayerSlug = (slug: string): string => {
  let decodedSlug = slug;

  try {
    decodedSlug = decodeURIComponent(slug);
  } catch {
    decodedSlug = slug;
  }

  return decodedSlug.replace(/-(\d+)$/, "#$1");
};

const LOCAL_HERO_SLUGS = new Set([
  "ana", "ashe", "baptiste", "bastion", "brigitte", "cassidy", "doomfist", "dva",
  "genji", "hanzo", "hazard", "illari", "junker-queen", "junkrat", "juno", "kiriko",
  "lifeweaver", "lucio", "mauga", "mei", "mercy", "moira", "orisa", "pharah",
  "reaper", "reinhardt", "roadhog", "sigma", "sojourn", "soldier-76", "sombra",
  "symmetra", "torbjorn", "tracer", "venture", "widowmaker", "winston", "wrecking-ball",
  "zarya", "zenyatta"
]);

export const getHeroIconUrl = (slug: string, imagePath?: string | null): string => {
  if (imagePath) {
    return imagePath;
  }
  if (LOCAL_HERO_SLUGS.has(slug)) {
    return `/avatar/${slug}.jpg`;
  }
  return `/avatar/0.png`;
};

