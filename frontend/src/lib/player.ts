import type { CatalogEntityChip } from "@/types/catalog.types";
import { PersonDisplay, User, UserProfile } from "@/types/user.types";
import { rosterRoleRank, type RoleOntology } from "@/lib/roster/ontology";
import { subRoleOf, type RoleRef } from "@/lib/roster/role-ref";

/**
 * Fields `sortTeamPlayers` actually reads. Display-only roster fields
 * (`characters`, `avg_mvp`, …) are intentionally excluded from the sort constraint.
 */
export interface SortableRosterPlayer {
  id: number;
  role: RoleRef | null;
  rank: number | null;
  is_substitution: boolean;
  related_player_id: number | null;
  relative_player?: number | null;
}

/** Minimal shape required for `sortTeamPlayers` / TournamentTeamTable rendering. */
export interface TeamRosterPlayer extends SortableRosterPlayer {
  name: string;
  /** What the roster's surface shows for this person; `display.canonical` builds the profile link. */
  display: PersonDisplay;
  division: number | null;
  is_newcomer: boolean;
  is_newcomer_role: boolean;
  /** Owning user id — set on user-scoped rosters so a table can flag "you". */
  user_id?: number;
  /** Average MVP placement across the player's matches (1 = MVP/best). */
  avg_mvp?: number | null;
  /** Player's top signature characters (catalog refs, or chips of a declared pick): the strip draws name and image. */
  characters?: Pick<CatalogEntityChip, "name" | "image_path">[];
}

type PlayerRoleInfo = {
  role: RoleRef | null;
};

export const formatSubRoleLabel = (subRole: string | null | undefined) => {
  if (!subRole) {
    return null;
  }

  return subRole
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
};

export const getPlayerType = (player: PlayerRoleInfo) => {
  const subRoleLabel = formatSubRoleLabel(subRoleOf(player.role));
  if (subRoleLabel) {
    return subRoleLabel;
  }
  return "ㅤ";
};

/** Highest rank first; an unranked player sorts last. */
const byRankDesc = (a: SortableRosterPlayer, b: SortableRosterPlayer): number => {
  if (a.rank == null || b.rank == null) return a.rank == null ? (b.rank == null ? 0 : 1) : -1;
  return b.rank - a.rank;
};

/**
 * The roster in reading order: each starter, then everyone who replaced them; starters ordered by the OWNER game's
 * declared role order (`ontology`), then by rank. Without a dictionary every role ranks equally, so the order is by
 * rank alone -- never a fixed role vocabulary.
 */
export const sortTeamPlayers = <P extends SortableRosterPlayer>(players: P[], ontology: RoleOntology | null): P[] => {
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
    list.sort(byRankDesc);
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

  // Sort roots by the owner game's declared role order, then by rank within the same role
  const roleRank = rosterRoleRank(ontology);
  roots.sort((a, b) => {
    const rp = roleRank(a.role) - roleRank(b.role);
    if (rp !== 0) return rp;
    return byRankDesc(a, b);
  });

  // Flatten: each root followed by its substitution chain
  return roots.flatMap(flatten);
};

export const getPlayerImage = (profile: UserProfile, user: User) =>
  // A user-uploaded avatar takes precedence over the most played character's portrait.
  user.avatar_url ?? profile.most_played_character?.image_path ?? `/avatar/${user.id % 10}.png`;

export const getPlayerSlug = (battleTag: string | null | undefined) => {
  if (!battleTag) {
    return "";
  }
  return battleTag.replace("#", "-");
};

/**
 * `Name#1234` → `{ name: "Name", suffix: "#1234" }`, splitting at the LAST `#` so a name that itself contains one
 * keeps it. A handle without a discriminator (or one that is only `#…`) comes back whole with a `null` suffix.
 */
export const splitHandle = (handle: string): { name: string; suffix: string | null } => {
  const index = handle.lastIndexOf("#");
  if (index <= 0) return { name: handle, suffix: null };
  return { name: handle.slice(0, index), suffix: handle.slice(index) };
};

/** A canonical `players.user.name` as a `PersonDisplay`: what cross-game surfaces (profile, mixed lists) show. */
export const canonicalDisplay = (name: string): PersonDisplay => {
  const { name: shown, suffix } = splitHandle(name);
  return { name: shown, tag: suffix, canonical: name, snapshot: null };
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
