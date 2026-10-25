import type { ComponentType, LazyExoticComponent, ReactNode } from "react";

import type { PickBanClassGroup, PickBanClassItem } from "@/components/pick-ban/pick-ban-model";
import type { PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type {
  DisciplineCapabilities,
  DisciplineMetadata,
  NativeTier
} from "@/types/discipline.types";
import type { EncounterTeam, MatchWithStats } from "@/types/encounter.types";
import type {
  CharacterSummary,
  CharacterWithUserStats,
  MatchWithUserStats,
  UserMapCharacterStats,
  UserMapRead,
  UserTournamentEntry
} from "@/types/user.types";
import type { UserTournamentStat } from "@/types/statistics.types";

import type { WorkspaceAxis } from "@/lib/site/discipline-scope";

export type { DisciplineCapabilities };

/** A run of native ranks as indices into the discipline's native ladder (0 = top rank), `from <= to`. */
export type NativeRankRange = { from: number; to: number };

/** One committed action of a round's character-ban phase, resolved against the catalog. */
export interface PregameCharacterAction {
  itemId: number;
  /** Catalog name, or the room's `#id` fallback while it loads. */
  name: string;
  /** Undefined until the character catalog resolves — the thumb falls back to initials. */
  item: PickBanItemLike | undefined;
  /** The character's class (`attrs.class`), only used to order a team's rows; null when the catalog knows none. */
  group: string | null;
  action: "ban" | "protect";
  /** The participation (`EncounterTeam.id`) that committed it. */
  teamId: number;
  /**
   * The earlier map this ban was spent on, when its `lifetime` still covers
   * this one. Nobody acted on it here, so it is badged with its origin rather
   * than read as a ban of this round.
   */
  carriedFromRound: number | null;
}

/** One character off on a map, as the final bans list shows it. */
interface PregameBannedCharacter extends PickBanClassItem {
  /** Undefined until the character catalog resolves — the thumb falls back to initials. */
  item: PickBanItemLike | undefined;
}

/** One map's character board: who banned what, and the final bans. */
export interface PregameCharacterBoard {
  /** Null for a flat (round-less) pool: one set of bans covered every map. */
  round: number | null;
  actions: PregameCharacterAction[];
  /** Every ban in force on this map, class-grouped — what the lobby disables. */
  banned: PickBanClassGroup<PregameBannedCharacter>[];
}

/** One map's worth of character actions, for replaying a finished series. */
export interface PregameCharacterRound extends PregameCharacterBoard {
  /** Null alongside a null round — there is no single map to name. */
  mapName: string | null;
  /** The map's catalog entry, for its still. Undefined until the catalog loads. */
  mapItem: PickBanItemLike | undefined;
}

/** What the character-comparison slot is given (the host's checked selection and read scope). */
export interface CharacterCompareProps {
  character: CatalogEntityRead | undefined;
  tournamentId: number | undefined;
  axis: WorkspaceAxis;
  metadata: DisciplineMetadata;
  /** The sample floor: a player with fewer games on the character is left off the board and its figures. */
  minGames: number;
  /** Moves the floor (the board's way back to the players it leaves off). */
  onMinGamesChange: (value: number) => void;
}

/** What a game's analytics board hands back to the host's tournament hero (slice 9 amendment). */
export interface AnalyticsHeroParts {
  /** The loaded result's team and player counts, for the hero's meta line; absent until it has loaded. */
  counts?: { teams: number; players: number } | null;
  /** The board's one-paragraph reading of the result: the hero's lede. */
  lede?: ReactNode;
  /** The board's headline figures (`HeroStat`s), the hero's right column. */
  stats?: ReactNode;
  /** The board's hero actions (its "how to read this" guide). */
  actions?: ReactNode;
  /** The board's own controls (its ranking picker), rendered beside the host's tournament picker. */
  controls?: ReactNode;
}

export type SlotProps = {
  /**
   * A character's hover card on the Maps tab (8b amendment: the host passes the figures it already read — the map's
   * per-character records and the player's winrate on the whole map — and the module draws its game's presentation).
   */
  characterPopover: {
    entity: CatalogEntityRead;
    mapStats: UserMapCharacterStats;
    /** Every character the player played on this map, `mapStats`' own included. */
    mapCharacters: UserMapCharacterStats[];
    /** The player's winrate (0..1) on the whole map. */
    mapWinRate: number;
    metadata: DisciplineMetadata;
  };
  /**
   * The profile's characters tab (8b amendment: the host reads the player's characters and maps once, in the
   * profile's game, and owns the tournament filter it passes as `filterSlot`).
   */
  characterStats: {
    characters: CharacterWithUserStats[];
    /** The player's maps with their per-character records; `undefined` while the read is in flight. */
    maps: UserMapRead[] | undefined;
    /** Set when the maps read failed: retries it. */
    retryMaps?: () => void;
    filterSlot?: ReactNode;
    metadata: DisciplineMetadata;
  };
  /**
   * The overview's most-played characters (8b addition). `characters` carry their game record and one career-best
   * `record`, but no per-stat best records.
   */
  topCharacters: {
    characters: CharacterSummary[];
    userSlug: string;
    metadata: DisciplineMetadata;
  };
  /** Under the overview's role split: one signature character per listed rated-dimension role code (8b addition). */
  roleSignatures: {
    characters: CharacterSummary[];
    roles: string[];
    metadata: DisciplineMetadata;
  };
  /** An extra cell of a tournament (or league) dossier's summary strip, over the player's entries and their runs (8b
   *  addition). */
  tournamentSummary: { entries: UserTournamentEntry[]; metadata: DisciplineMetadata };
  /**
   * The lobby-rank tiles of the overview's tournament card (slice 11): the game's own selection, order and
   * presentation of the ranked tournament `stats` (keyed by stat code); `onOpen` opens the lobby leaderboard of one.
   */
  lobbyRankTiles: {
    stats: Record<string, UserTournamentStat | undefined>;
    onOpen: (stat: string, label: string) => void;
    metadata: DisciplineMetadata;
  };
  /**
   * The character comparison (`/users/heroes-compare`), 8b fix amendment: the host owns the browsed game, the
   * checked character (`undefined` until one is picked and found in that game), the tournament scope and the sample
   * floor; the module reads that character's leaderboard itself (its wire and column catalog are the module's) and
   * draws everything under the picker: the hero card, the top chart and the board. A game without a renderer gets
   * the host's explicit "not available" state and no read.
   */
  characterCompare: CharacterCompareProps;
  matchStats: { match: MatchWithStats; metadata: DisciplineMetadata };
  /** `view`: `overview` compares the observed sides; `players` is the totals grouped by participation (8a amendment). */
  seriesStats: { matches: MatchWithStats[]; metadata: DisciplineMetadata; view: "overview" | "players" };
  matchRowBadge: { match: MatchWithUserStats; metadata: DisciplineMetadata };
  /** The characters one player (by global `userId`) played in a match; the pick/ban target board's previous-map list (8a addition). */
  matchCharacters: { match: MatchWithStats; userId: number | null; metadata: DisciplineMetadata };
  /**
   * One tournament's analytics board (slice 9 amendment): the host resolves the owner tournament, its workspace and
   * game metadata and the viewer's analytics permissions; the module reads its own analytics wire, owns the ranking
   * choice (`?algorithm=`) and renders the host's tournament hero through `hero`, so the page keeps one header.
   */
  analytics: {
    tournamentId: number;
    workspaceId: number;
    metadata: DisciplineMetadata;
    /** The viewer may read the permission-gated ML reads of the owner workspace. */
    canReadV2: boolean;
    /** The viewer may recalculate / edit analytics. */
    canUpdate: boolean;
    /** The tournament has ended: its places 1–3 are medals (DESIGN.md §2). */
    ended: boolean;
    hero: (parts: AnalyticsHeroParts) => ReactNode;
  };
  nativeRankEditor: {
    ladder: NativeTier[];
    value: NativeRankRange | null;
    onChange(value: NativeRankRange | null): void;
    disabled?: boolean;
    /** Per ladder rank, the name of the division that already holds it (`null` = unlinked). Display only. */
    owners?: readonly (string | null)[];
    /** Accessible name of the division being edited. */
    label?: string;
  };
  rankHistory: {
    userId: number;
    axis: WorkspaceAxis;
    discipline: string;
    /** `false` inside a card that already frames the chart: no tiles or chart box of its own. */
    framed?: boolean;
  };
  /**
   * The room's character bans for one map (or the whole series when the pool is flat). Class order comes
   * from `metadata.discipline.character_classes`.
   */
  pregameCharacterBans: {
    encounterId: number;
    metadata: DisciplineMetadata;
    board: PregameCharacterBoard;
    /** The encounter's live seats: a column each, with the source team's logo when the read carried it. */
    teams: EncounterTeam[];
    /** Replaces the default caption; `null` drops it (the closing screen captions each row itself). */
    eyebrow?: ReactNode | null;
    /** Replaces the lobby-setup hint; `null` drops it (it only applies before a map is played). */
    hint?: string | null;
  };
};

export type DisciplineSlot = keyof SlotProps;

/**
 * Slot families. Each family has its own registry and module entrypoint, so a host reaches (and its i18n zone
 * ships) only the code of the slots it can render. A slot's owner adds it to exactly one family; never to a
 * catch-all one.
 */
export type RankSlot = "rankHistory";
export type ProfileSlot =
  | "characterPopover"
  | "characterStats"
  | "topCharacters"
  | "roleSignatures"
  | "tournamentSummary"
  | "lobbyRankTiles"
  | "characterCompare";
export type MatchSlot = "matchStats" | "seriesStats" | "matchRowBadge" | "matchCharacters";
export type PregameSlot = "pregameCharacterBans";
export type AdminSlot = "nativeRankEditor";
export type AnalyticsSlot = "analytics";

/** One module's lazy renderers for the slots of family `S`. */
export interface DisciplineUI<S extends DisciplineSlot = DisciplineSlot> {
  code: string;
  slots: Partial<{ [K in S]: LazyExoticComponent<ComponentType<SlotProps[K]>> }>;
}
