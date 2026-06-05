import { Player } from "@/types/team.types";
import { User, UserProfile } from "@/types/user.types";

/** Minimal shape required for `sortTeamPlayers` / TournamentTeamTable rendering. */
export interface TeamRosterPlayer {
  id: number;
  name: string;
  role: string | null;
  sub_role: string | null;
  rank: number;
  division: number;
  is_substitution: boolean;
  is_newcomer: boolean;
  is_newcomer_role: boolean;
  related_player_id: number | null;
  relative_player?: number | null;
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

export const sortTeamPlayers = <P extends TeamRosterPlayer>(players: P[]): P[] => {
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
  if (profile.most_played_hero === null) {
    return `/avatar/${user.id % 10}.png`;
  }

  // if (["mauga", "juno", "junker-queen", "kiriko", "lifeweaver", "baptiste", "sojourn", "echo", "ramattra", "wrecking-ball", "venture", "illari", "ashe", "hazard"].includes(slug)) {
  //   return `/avatar/${profile.user.id % 10}.png`;
  // }
  return `/avatar/${profile.most_played_hero.slug}.jpg`;
  // return profile.most_played_hero.image_path
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

