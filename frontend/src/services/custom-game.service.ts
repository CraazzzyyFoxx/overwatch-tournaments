import { apiFetch } from "@/lib/api/fetch";
import { blobToBase64 } from "@/lib/image-capture";
import type { RoleCode } from "@/lib/roster/roles";
import type { RosterShape } from "@/lib/roster/shape";
import type { DiscordVoicePermission } from "@/types/discord.types";

/** Where an effective rank came from, strongest first. */
export type RankSource = "author" | "workspace" | "ow";

export const RANK_SOURCE_LABELS: Record<RankSource, string> = {
  author: "Mine",
  workspace: "Workspace",
  ow: "Overwatch",
};

/**
 * One row of a mix lineup, self-describing so the lineup never has to guess a
 * name from a separately paginated pool query.
 *
 * Ranks come from three layers and the row carries enough to tell them apart:
 * `ranks` is what balance will actually use, `rank_sources` says which layer won
 * (this host's own book > the workspace canon > Overwatch), and `author_ranks`
 * is this host's book alone so the sheet can edit it without mistaking an
 * inherited value for their own. There is deliberately no per-mix pin: a rank
 * that only existed inside one mix was invisible everywhere else it mattered.
 */
/** Where a lineup row stands: one field, three states, no impossible pair. */
export type MixParticipation = "must_play" | "pool" | "benched";

/**
 * How `roles` is read. `all_ranked` means the server derives the playable roles
 * from whatever this row is ranked for (`roles` is `null`); `explicit` means
 * `roles` is the host's own ordered list -- an empty list included, which is
 * "plays nothing" rather than "plays everything".
 */
export type MixRoleSelectionMode = "all_ranked" | "explicit";

export type CustomGamePlayer = {
  id: number;
  workspace_member_id: number;
  display_name: string | null;
  battle_tag: string | null;
  sort_order: number;
  participation: MixParticipation;
  role_selection_mode: MixRoleSelectionMode;
  /** Every role this row has a rank for is treated as equally preferred by
   * the solver, so `roles`'s order stops mattering as a priority hint --
   * mirrors the tournament balancer's flex flag (`Player.is_flex`). */
  is_flex: boolean;
  /**
   * Which lobby this player is seated in right now, derived server-side from
   * the selected variant of each lobby; `null` means waiting for a seat.
   * Detail reads only.
   */
  current_lobby?: number | null;
  /** The host's own tie to a lobby, independent of where the balance seated them. */
  lobby_pin?: number | null;
  /** `null` only when `role_selection_mode === "all_ranked"`. */
  roles: string[] | null;
  ranks: Record<string, number>;
  rank_sources: Record<string, RankSource>;
  author_ranks: Record<string, number>;
};

export type CustomGameStatus = "draft" | "balanced" | "completed" | "cancelled";

/**
 * How a match ended. `winner` is a 1-based team number, `null` a draw.
 */
export type CustomGameOutcome = {
  winner: 1 | 2 | null;
};

/** An account with the same write access as the mix's host. */
export type CustomGameCoHost = {
  /** `auth.user.id` -- the identity every write endpoint addresses, host included. */
  user_id: number;
  display_name: string | null;
};

/**
 * What the mix itself still carries. Each one is a stored fact with its own
 * type -- there is no config blob to parse, and no key that can silently mean
 * two things.
 *
 * Everything that describes how a host RUNS a mix -- roster shape, solver
 * knobs, the rank points a win is worth -- lives on their account instead
 * (`/api/v1/balancer/me/mix-preferences`), and the Discord target is the
 * workspace's. What is left here is the mix's own state.
 */
export type CustomGameSettings = {
  /**
   * The host's rank-adjustment-per-win, resolved server-side and read-only
   * here: the win buttons print it, the host changes it in account settings.
   * Always a number -- `0` is the knob switched off, and recording a result
   * then leaves every rank alone.
   */
  points_per_win: number;
  /** Host overrides keyed by 0-based team index. Absent index = computed default. */
  team_names: Record<string, string>;
  /**
   * The workspace-wide mix channel -- where `postToDiscord` sends the matchup,
   * and the only channel a mix can post to. Set by workspace admins in the
   * workspace's Discord settings; `null` means the workspace named none and
   * there is nothing to post to.
   */
  workspace_discord_channel_id: string | null;
};

/**
 * One lobby of a mix — the four columns that used to sit on the mix itself
 * (`custom_game_lobby`). A mix always has exactly `lobby_count` of them, so
 * lobby 0 is an ordinary row rather than a special case, and every further
 * lobby carries its own document, its own pager position and its own next map.
 */
export type CustomGameLobby = {
  /** 0-based: 0 = A … 5 = F. Also the offset of this lobby's team names: `lobby_index * 2 + team`. */
  lobby_index: number;
  /**
   * The solver's own document for this lobby's last balance, or `null` before
   * one. Detail reads only -- `list` rows leave it out (it runs to megabytes).
   */
  balance_result?: unknown;
  /** Which option of this lobby's `balance_result` the mix is showing. */
  selected_variant_index: number;
  /** The map this lobby's next match is played on; cleared by recording it. */
  next_map_id: number | null;
  /** When this lobby was last balanced, or `null` while it never was. */
  balanced_at: string | null;
  /**
   * The voices this lobby's two teams are moved into (`^\d{1,20}$` snowflakes,
   * `null` while unpicked). Both list and detail reads carry them: the list is
   * how the page tells which voices the workspace's other mixes already took.
   */
  team1_voice_channel_id: string | null;
  team2_voice_channel_id: string | null;
  /**
   * `false` when this lobby has been balanced and no match of its own has been
   * recorded since -- the lineup on screen is still unplayed, so anything that
   * would overwrite it asks first. Detail reads only.
   */
  lineup_recorded?: boolean;
  /** How many matches this lobby has recorded. Detail reads only. */
  matches_count?: number;
};

/**
 * One Discord message the platform posted on a mix's behalf -- a
 * `discord_message` row of subject `mix:<id>`. `slot` says which post it is:
 * `signup`, or `lineup:<lobby_index>:<game number>` for a lineup card.
 * `lost` is server-derived: still `pending` past the bot queue's TTL, so the
 * command expired before the bot ever saw it.
 */
export type CustomGameDiscordPost = {
  id: number;
  slot: string;
  kind: "mix.signup" | "mix.lineup";
  status: "pending" | "posted" | "failed" | "deleting" | "lost";
  /** Jump link once posted; `null` before that or while the workspace has no guild id. */
  url: string | null;
  /** Discord's refusal text when the post failed (usually missing channel permissions). */
  error: string | null;
  created_at: string;
};

export type CustomGame = {
  id: number;
  workspace_id: number;
  host_user_id: number;
  /** Extra workspace members who write this mix exactly like the host (see `custom.add_co_host`). */
  co_hosts: CustomGameCoHost[];
  host_display_name: string | null;
  name: string;
  status: CustomGameStatus;
  settings: CustomGameSettings;
  created_at: string | null;
  /** How many lobbies this mix runs at once; 6 is the ceiling (CHECK server-side). */
  lobby_count: number;
  /**
   * This mix's lobbies, ordered by `lobby_index` -- exactly `lobby_count` of
   * them. The balance document, the pager position and the next map all live
   * here now; the mix itself carries none of the three.
   */
  lobbies: CustomGameLobby[];
  /**
   * The mix's resolved team composition -- the host's own shape preference,
   * else the workspace default, else the built-in Overwatch 5v5 shape.
   */
  roster_shape: RosterShape | null;
  /** How many matches this mix has recorded -- the list's activity read, without loading the history. */
  matches_count: number;
  /** When the newest match was recorded, or `null` while none has been. */
  last_match_at: string | null;
  /** Whether players may sign themselves up, and where a signup lands. */
  self_signup: MixSelfSignup;
  /** Whether a player on the roster may reorder their own roles and flex. */
  self_role_edit: boolean;
  /**
   * The voice everyone waits in and is returned to, picked from the
   * workspace's general voices (`mix_general_voice_channel_ids`).
   */
  general_voice_channel_id: string | null;
  /**
   * Every Discord message the platform posted for this mix (signup card,
   * lineup cards), oldest first, minus the ones already deleted. Optional
   * only so fixtures predating the posts can omit it -- the server always
   * sends the list.
   */
  discord_posts?: CustomGameDiscordPost[];
  players?: CustomGamePlayer[];
};

/** One voice channel of the workspace's mix category, with the bot's gaps on it. */
export type MixVoiceChannel = {
  id: string;
  name: string;
  /** `null` when Discord was not asked about it; an empty list means nothing is missing. */
  missing_permissions: DiscordVoicePermission[] | null;
};

/**
 * The voices a mix may pick, read from the workspace's category. `error` is
 * Discord's own refusal: the category stays configured, it just could not be
 * listed right now.
 */
export type MixVoiceOptions = {
  category_id: string | null;
  category_missing_permissions: DiscordVoicePermission[] | null;
  /** Voices the workspace calls general -- where players wait and are returned to. */
  general: MixVoiceChannel[];
  /** Every other voice of the category: what a lobby's two teams are moved into. */
  team: MixVoiceChannel[];
  error: string | null;
};

/** What became of one player in a move or a return. */
export type MixVoiceStatus =
  | "moved"
  | "not_in_voice"
  | "no_discord_link"
  | "missing_permission"
  | "channel_outside_category"
  | "not_configured"
  | "failed";

/** One move or return, player by player. `moved` counts the `moved` rows. */
export type MixVoiceReport = {
  moved: number;
  results: {
    workspace_member_id: number | null;
    name: string;
    status: MixVoiceStatus;
    channel_id: string | null;
  }[];
};

/** The mix's whole voice setup: the endpoint replaces it rather than patching a field. */
export type MixVoicePatch = {
  general_voice_channel_id: string | null;
  lobbies: {
    lobby_index: number;
    team1_voice_channel_id: string | null;
    team2_voice_channel_id: string | null;
  }[];
};

/**
 * One match recorded by `recordOutcome`, as it comes back from the permanent
 * `casual.match` log -- the only record of a played match. `winner` is derived
 * server-side from the scoreline, the same 1-based/`null` shape as
 * `CustomGameOutcome`.
 */
export type CustomGameMatch = {
  id: number;
  home_team_name: string;
  away_team_name: string;
  home_score: number;
  away_score: number;
  winner: number | null;
  map_id: number | null;
  map_name: string | null;
  map_image_path: string | null;
  recorded_by: number | null;
  recorded_at: string | null;
  /** Which lobby of the mix played it (0-based, 0 = A). A one-lobby mix records only 0. */
  lobby_index: number;
  /**
   * The rank points this match moved each player by when it was recorded --
   * `null` for a draw, or when the mix had no rank adjustment configured. An
   * undo rolls back by this, never by the mix's current `points_per_win`.
   */
  points_per_win_applied: number | null;
};

/** Patch semantics: an omitted key is left untouched on the server. */
export type CustomGamePlayerPatch = {
  participation?: MixParticipation;
  roles?: string[] | null;
  is_flex?: boolean;
  /**
   * Which lobby this player is tied to, or `null` for "wherever the balance
   * puts them". Host-only, and 422 on a mix that runs one lobby.
   */
  lobby_pin?: number | null;
};

/**
 * Whether players may sign themselves up, and where they land when they do --
 * one column with exactly three states (`custom_game.self_signup`), so
 * "closed but benched" cannot be expressed at all.
 */
export type MixSelfSignup = "closed" | "pool" | "benched";

/**
 * Why a self-action is refused, exactly as `mix_self_policy` names it. The wire
 * carries the code, never a sentence: the site renders it per locale
 * (`mixes.self.blocker.*`) and the bot renders the same code its own way.
 */
export type MixSelfBlocker =
  | "mix_closed"
  | "discord_not_linked"
  | "battlenet_not_linked"
  | "player_not_linked"
  | "self_join_denied"
  | "already_joined"
  | "not_on_roster"
  | "signup_closed"
  | "roster_full"
  | "role_edit_off";

/** The caller's own roster row, or `null` when they are not in the lineup. */
export type MixSelfSeat = {
  participation: MixParticipation;
  /** `null` is the `all_ranked` mode -- every role this player has a rank for. */
  roles: string[] | null;
  is_flex: boolean;
  /** Effective rank per role; `null` where no layer answers for it. */
  ranks: Record<string, number | null>;
  /** Which lobby a balance seated them in; `null` means waiting for a seat. */
  current_lobby: number | null;
};

/** What the caller may do, and the first reason they may not. */
export type MixSelfPolicy = {
  can_join: boolean;
  can_leave: boolean;
  can_edit_roles: boolean;
  /** `null` exactly when `can_join`. */
  join_blocker: MixSelfBlocker | null;
  /** `null` exactly when `can_edit_roles`. */
  edit_blocker: MixSelfBlocker | null;
};

/**
 * The whole self surface of one mix in a single read (`GET …/me`).
 *
 * Kept apart from `CustomGame` on purpose: the mix board is public and its
 * detail is the same document for every viewer, while this answer is about the
 * caller -- their seat, their missing account links, their permission.
 */
export type MixSelfState = {
  custom_game_id: number;
  name: string;
  status: CustomGameStatus;
  self_signup: MixSelfSignup;
  self_role_edit: boolean;
  /** How many lobbies the mix runs; with one, `seat.current_lobby` says nothing. */
  lobby_count: number;
  seat: MixSelfSeat | null;
  /** Roles this player would play that no rank layer answers for. */
  unranked_roles: string[];
  policy: MixSelfPolicy;
};

/** One row of a whole-lineup participation write. */
export type CustomGameParticipationEntry = {
  workspace_member_id: number;
  participation: MixParticipation;
};

/** A pool member's fairness-rotation verdict for the next map, from `rotation`. */
export type RotationStatus = "must_play" | "should_rest" | "neutral";

/**
 * One roster row's rotation-fairness read, computed server-side from this
 * mix's own map history (see `mix_rotation.recommend_rotation`). Read-only --
 * a host acts on it through the same `participation` field.
 */
export type RotationRecommendation = {
  workspace_member_id: number;
  status: RotationStatus;
  reason: string;
  consecutive_sat: number;
  consecutive_played: number;
  games_played: number;
};

/** One role's slice of a member's mix record. Absent from `by_role` when that role never played. */
export type MixRoleTally = {
  games: number;
  wins: number;
  losses: number;
  draws: number;
};

/**
 * One workspace member's record across every mix this workspace has run,
 * counted from the permanent casual-match log -- one recorded seat is one
 * game, its outcome the scoreline of the team it sat in. A member who has
 * since left the roster keeps their rows: the id stays, `display_name` falls
 * to null.
 */
export type MixMemberStats = {
  workspace_member_id: number;
  display_name: string | null;
  battle_tag: string | null;
  games: number;
  wins: number;
  losses: number;
  draws: number;
  /** `wins / games` as a share, not a percentage; 0 when nothing was played. */
  win_rate: number;
  /** The run from the newest match: `+n` consecutive wins, `-n` losses, 0 after a draw. */
  streak: number;
  last_played_at: string | null;
  /** Only roles with games played -- a seat with no role counts in the totals and in no bucket. */
  by_role: Partial<Record<"tank" | "damage" | "support", MixRoleTally>>;
};

/** `since` echoes back the window the server parsed, so a reader can tell it from all time. */
export type MixStatsResponse = {
  since: string | null;
  members: MixMemberStats[];
};

export const customGameKeys = {
  /** Every mix query for a workspace — `list` is a prefix of the rest, so this covers them all. */
  all: (workspaceId: number) => ["custom-games", workspaceId] as const,
  list: (workspaceId: number) => ["custom-games", workspaceId] as const,
  one: (workspaceId: number, gameId: number) => ["custom-games", workspaceId, gameId] as const,
  byId: (gameId: number, workspaceId: number | null) =>
    ["custom-game-entity", gameId, workspaceId] as const,
  matches: (workspaceId: number, gameId: number) => ["custom-games", workspaceId, gameId, "matches"] as const,
  /**
   * Every lobby's rotation queue for one mix — the prefix the per-lobby keys
   * hang off, so a write that moves the queue drops every lobby in one call.
   */
  rotationAll: (workspaceId: number, gameId: number) =>
    [...customGameKeys.one(workspaceId, gameId), "rotation"] as const,
  /** One lobby's queue: the candidates of lobby A are not the candidates of lobby B. */
  rotation: (workspaceId: number, gameId: number, lobbyIndex: number) =>
    ["custom-games", workspaceId, gameId, "rotation", lobbyIndex] as const,
  /**
   * The caller's own seat in one mix. Deliberately under `all`: the realtime
   * `workspace.pickup_mix` resource drops `customGameKeys.all(workspaceId)`
   * (`lib/realtime/resources.ts`), so another player's join refreshes this
   * read with no subscription of its own.
   */
  me: (workspaceId: number, gameId: number) => ["custom-games", workspaceId, gameId, "me"] as const,
  /**
   * The voices one mix may pick. Under `all` like `me`: a workspace that
   * re-picks its voice category drops every mix key anyway.
   */
  voiceOptions: (workspaceId: number, gameId: number) =>
    ["custom-games", workspaceId, gameId, "voice-options"] as const,
  stats: (workspaceId: number, since: string | null) =>
    ["custom-games", workspaceId, "stats", since ?? "all"] as const,
};

export const customGameService = {
  list(workspaceId: number): Promise<CustomGame[]> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games`, { skipWorkspace: true }).then((r) => r.json());
  },

  /**
   * Starts empty: the lineup is built explicitly from the workspace roster.
   * `cloneFromGameId` instead copies a previous mix's lineup and settings --
   * everyone lands in the pool, and no match history comes with it.
   */
  create(workspaceId: number, name: string, cloneFromGameId: number | null = null): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games`, {
      skipWorkspace: true,
      method: "POST",
      body: {
        name,
        member_ids: [],
        ...(cloneFromGameId != null ? { clone_from_game_id: cloneFromGameId } : {}),
      },
    }).then((r) => r.json());
  },

  getById(gameId: number, workspaceId: number | null = null): Promise<CustomGame> {
    const query = workspaceId == null ? "" : `?workspace_id=${workspaceId}`;
    return apiFetch(`/api/v1/balancer/custom-games/${gameId}${query}`, { skipWorkspace: true }).then((r) => r.json());
  },

  updateRoster(workspaceId: number, gameId: number, memberIds: number[]): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/roster`, {
      skipWorkspace: true,
      method: "POST",
      body: { member_ids: memberIds },
    }).then((r) => r.json());
  },

  updatePlayer(
    workspaceId: number,
    gameId: number,
    workspaceMemberId: number,
    patch: CustomGamePlayerPatch,
  ): Promise<CustomGame> {
    return apiFetch(
      `/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/players/${workspaceMemberId}`,
      { skipWorkspace: true, method: "PUT", body: patch },
    ).then((r) => r.json());
  },

  /**
   * One request for a whole-lineup move (the rotation hint applies several rows
   * at once). Atomic server-side, so there is no half-applied verdict and no
   * race between per-row responses.
   */
  setParticipation(
    workspaceId: number,
    gameId: number,
    players: CustomGameParticipationEntry[],
  ): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/players`, {
      skipWorkspace: true,
      method: "PUT",
      body: { players },
    }).then((r) => r.json());
  },

  /**
   * Re-runs the solver. `scope: "lobby"` balances that lobby alone, leaving
   * every other document, map and pager untouched, and its candidates exclude
   * whoever another lobby has seated or holds a pin on. `scope: "all"` splits
   * the whole pool into equally strong lobbies and solves each -- mixes running
   * more than one lobby only (422 `single_lobby` otherwise), and 422
   * `not_enough_players` when the pool cannot fill them all.
   */
  balance(
    workspaceId: number,
    gameId: number,
    request: { scope: "lobby"; lobbyIndex: number } | { scope: "all" },
  ): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/balance`, {
      skipWorkspace: true,
      method: "POST",
      body:
        request.scope === "all"
          ? { scope: "all" }
          : { scope: "lobby", lobby_index: request.lobbyIndex },
    }).then((r) => r.json());
  },

  /**
   * Snapshots one played match of one lobby into the permanent casual-match log
   * — team rosters and who won. Repeatable: a mix can record many before its
   * host calls `close`. `variantIndex` is whichever balance option that lobby is
   * showing; the map is that lobby's `next_map_id`, consumed server-side.
   */
  recordOutcome(
    workspaceId: number,
    gameId: number,
    lobbyIndex: number,
    outcome: CustomGameOutcome,
    variantIndex: number,
  ): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/outcome`, {
      skipWorkspace: true,
      method: "POST",
      body: { lobby_index: lobbyIndex, outcome, variant_index: variantIndex },
    }).then((r) => r.json());
  },

  /** Every match this mix has recorded, newest first. */
  listMatches(workspaceId: number, gameId: number): Promise<CustomGameMatch[]> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/matches`, { skipWorkspace: true }).then((r) => r.json());
  },

  /**
   * Takes the newest match back out of the log -- only the newest, so the
   * rollback never has to reason about what a later match did on top of it.
   * Ranks move back by the points that match itself applied
   * (`points_per_win_applied`), not by the mix's current setting. Players it
   * released from must-play stay in the pool: the seat they were owed was
   * spent, undoing the scoreline does not un-spend it.
   */
  undoMatch(workspaceId: number, gameId: number, matchId: number): Promise<CustomGame> {
    return apiFetch(
      `/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/matches/${matchId}`,
      { skipWorkspace: true, method: "DELETE" },
    ).then((r) => r.json());
  },

  /**
   * Who is owed the next seat in this lobby and who should rest, ranked from
   * the mix's own map history and split at the seat count a balance of THIS
   * lobby would fill right now. Read-only, feeds the lineup as a hint.
   */
  rotation(
    workspaceId: number,
    gameId: number,
    lobbyIndex: number,
  ): Promise<RotationRecommendation[]> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/rotation`, {
      skipWorkspace: true,
      query: { lobby_index: lobbyIndex },
    }).then((r) => r.json());
  },

  /**
   * Every member's win/loss record across this workspace's mixes, read from
   * the permanent match log rather than from any one mix. `since` (ISO) counts
   * only matches recorded from then on; `null` counts all time.
   */
  stats(workspaceId: number, since: string | null = null): Promise<MixStatsResponse> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/stats`, {
      skipWorkspace: true,
      // `apiFetch` drops a null query value, so all time sends no `since` at all.
      query: { since },
    }).then((r) => r.json());
  },

  /** Ends the mix. Matches already recorded stay recorded; this only stops further writes. */
  close(workspaceId: number, gameId: number): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/close`, {
      skipWorkspace: true,
      method: "POST",
    }).then((r) => r.json());
  },

  /**
   * Permanently deletes the mix and every match it recorded. Workspace admin
   * only -- unlike `close` (a host-triggered status flip) this is irreversible.
   */
  hardDelete(workspaceId: number, gameId: number): Promise<void> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}`, {
      skipWorkspace: true,
      method: "DELETE",
    }).then(() => undefined);
  },

  /**
   * Patch semantics: an index left out of ``teamNames`` keeps its current
   * name; an empty string clears that team's override back to the computed
   * default (``Team N``).
   */
  setTeamNames(workspaceId: number, gameId: number, teamNames: Record<string, string>): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/team-names`, {
      skipWorkspace: true,
      method: "PUT",
      body: { team_names: teamNames },
    }).then((r) => r.json());
  },

  /**
   * Names the map this lobby's next match is played on, or clears it (`null`).
   * The roll itself happens client-side (`rollNextMap`); this stores the verdict
   * so co-hosts and viewers see the same map and `recordOutcome` stamps it.
   */
  setNextMap(
    workspaceId: number,
    gameId: number,
    lobbyIndex: number,
    mapId: number | null,
  ): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/next-map`, {
      skipWorkspace: true,
      method: "PUT",
      body: { lobby_index: lobbyIndex, map_id: mapId },
    }).then((r) => r.json());
  },

  /**
   * Pages one lobby to one of the options its last balance produced. Not a local
   * view toggle: the index is stored on the lobby, so co-hosts and viewers move
   * with the host. 404s an index past the stored options; 409 `seat_conflict`
   * when the option would seat somebody another lobby has already seated.
   */
  setVariantIndex(
    workspaceId: number,
    gameId: number,
    lobbyIndex: number,
    variantIndex: number,
  ): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/variant`, {
      skipWorkspace: true,
      method: "PUT",
      body: { lobby_index: lobbyIndex, variant_index: variantIndex },
    }).then((r) => r.json());
  },

  /**
   * Hands primary ownership to another workspace member. Any current writer
   * -- the host or a co-host -- may call this; it 403s the caller's very
   * next write here unless they are also a co-host, and opens every write
   * (roster, balance, outcomes, settings) to the new host.
   */
  transferHost(workspaceId: number, gameId: number, newHostUserId: number): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/host`, {
      skipWorkspace: true,
      method: "PUT",
      body: { new_host_user_id: newHostUserId },
    }).then((r) => r.json());
  },

  /**
   * Grants another workspace member the same write access as the host --
   * roster, balance, outcomes, settings, even transferring the host on. Any
   * current writer (host or existing co-host) may extend the list.
   */
  addCoHost(workspaceId: number, gameId: number, coHostUserId: number): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/co-hosts`, {
      skipWorkspace: true,
      method: "POST",
      body: { co_host_user_id: coHostUserId },
    }).then((r) => r.json());
  },

  /** Revokes a co-host's write access, including a co-host removing themselves. */
  removeCoHost(workspaceId: number, gameId: number, coHostUserId: number): Promise<CustomGame> {
    return apiFetch(
      `/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/co-hosts/${coHostUserId}`,
      { skipWorkspace: true, method: "DELETE" },
    ).then((r) => r.json());
  },

  /**
   * Swap two seated players between the teams of ONE lobby, same role only -- a
   * same-role swap can never break a team's role quota, so it needs no
   * eligibility check beyond "both exist and share a role". `variantIndex` edits
   * whichever balance option that lobby is showing, not always the first.
   */
  swapSeats(
    workspaceId: number,
    gameId: number,
    lobbyIndex: number,
    variantIndex: number,
    firstUuid: string,
    secondUuid: string,
  ): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/teams/swap`, {
      skipWorkspace: true,
      method: "POST",
      body: {
        lobby_index: lobbyIndex,
        variant_index: variantIndex,
        first_uuid: firstUuid,
        second_uuid: secondUuid,
      },
    }).then((r) => r.json());
  },

  /**
   * Posts one lobby's current matchup -- teams and its next map -- to the mix's
   * Discord channel. Fire-and-forget: the response only says the message was
   * queued for the bot. `variantIndex` is whichever balance option that lobby is
   * showing.
   *
   * `image` is that matchup rasterised in the browser; it is what the bot
   * attaches. Passing `null` (a capture that failed, or a caller with no node
   * to capture) posts the server's text embed instead.
   */
  async postToDiscord(
    workspaceId: number,
    gameId: number,
    lobbyIndex: number,
    variantIndex: number,
    image: Blob | null = null,
  ): Promise<{ status: "queued"; channel_id: string }> {
    const response = await apiFetch(
      `/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/discord/post`,
      {
        skipWorkspace: true,
        method: "POST",
        body: {
          lobby_index: lobbyIndex,
          variant_index: variantIndex,
          image_b64: image ? await blobToBase64(image) : null,
        },
      },
    );
    return response.json();
  },

  /**
   * How many lobbies this mix runs (1..6). Raising it opens empty lobbies for
   * the new indexes; lowering it drops the rows past the new count (their
   * balances are lost, their recorded matches stay in the history) and clears
   * every `lobby_pin` onto them.
   */
  setLobbyCount(workspaceId: number, gameId: number, lobbyCount: number): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/lobbies`, {
      skipWorkspace: true,
      method: "PUT",
      body: { lobby_count: lobbyCount },
    }).then((r) => r.json());
  },

  rename(workspaceId: number, gameId: number, name: string): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/name`, {
      skipWorkspace: true,
      method: "PUT",
      body: { name },
    }).then((r) => r.json());
  },

  /** The caller's own standing in this mix: seat, blockers, what they may do. */
  getMySeat(workspaceId: number, gameId: number): Promise<MixSelfState> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/me`, { skipWorkspace: true }).then((r) =>
      r.json(),
    );
  },

  /**
   * Signs the caller up. Idempotent: a caller already on the roster gets their
   * current state back rather than an error, so a second press never moves a
   * host's bench decision back into the pool.
   */
  joinMix(workspaceId: number, gameId: number): Promise<MixSelfState> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/me`, {
      skipWorkspace: true,
      method: "POST",
    }).then((r) => r.json());
  },

  /** Takes the caller out of the lineup. Allowed with no linked accounts at all. */
  leaveMix(workspaceId: number, gameId: number): Promise<MixSelfState> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/me`, {
      skipWorkspace: true,
      method: "DELETE",
    }).then((r) => r.json());
  },

  /**
   * The two fields a player owns on their own row. Same patch semantics as the
   * host's `updatePlayer` -- an omitted key is untouched, `roles: null` is the
   * `all_ranked` mode -- against a narrower server-side allow-list: anything
   * else (participation, ranks) is a 422.
   */
  updateMySeat(
    workspaceId: number,
    gameId: number,
    patch: { roles?: RoleCode[] | null; is_flex?: boolean },
  ): Promise<MixSelfState> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/me`, {
      skipWorkspace: true,
      method: "PATCH",
      body: patch,
    }).then((r) => r.json());
  },

  /** The host's two switches: who may sign up, and whether they may edit roles. */
  setSelfService(
    workspaceId: number,
    gameId: number,
    patch: { self_signup?: MixSelfSignup; self_role_edit?: boolean },
  ): Promise<CustomGame> {
    return apiFetch(
      `/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/self-service`,
      { skipWorkspace: true, method: "PUT", body: patch },
    ).then((r) => r.json());
  },

  /**
   * Opens signup in the requested mode and queues the signup card for the
   * workspace's mix channel. Fire-and-forget like `postToDiscord`: the response
   * only says the message reached the bot's queue.
   */
  postSignup(
    workspaceId: number,
    gameId: number,
    selfSignup: "pool" | "benched",
  ): Promise<{ status: "queued"; channel_id: string }> {
    return apiFetch(
      `/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/discord/signup`,
      { skipWorkspace: true, method: "POST", body: { self_signup: selfSignup } },
    ).then((r) => r.json());
  },

  /**
   * Removes one of the mix's Discord posts. The row flips to `deleting` and
   * the bot deletes the message asynchronously; the updated mix comes back.
   */
  deleteDiscordPost(workspaceId: number, gameId: number, postId: number): Promise<CustomGame> {
    return apiFetch(
      `/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/discord/posts/${postId}`,
      { skipWorkspace: true, method: "DELETE" },
    ).then((r) => r.json());
  },

  /** The voices this mix may pick, straight from the workspace's category. */
  voiceOptions(workspaceId: number, gameId: number): Promise<MixVoiceOptions> {
    return apiFetch(
      `/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/voice/options`,
      { skipWorkspace: true },
    ).then((r) => r.json());
  },

  /** Replaces the mix's whole voice setup -- general voice and every lobby's two. */
  setVoiceChannels(workspaceId: number, gameId: number, patch: MixVoicePatch): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/voice`, {
      skipWorkspace: true,
      method: "PUT",
      body: patch,
    }).then((r) => r.json());
  },

  /**
   * Moves one lobby's seated players into their team voices, or every lobby's
   * when `lobbyIndex` is `null`. The report says what became of each of them.
   */
  voiceMove(workspaceId: number, gameId: number, lobbyIndex: number | null): Promise<MixVoiceReport> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/voice/move`, {
      skipWorkspace: true,
      method: "POST",
      body: { lobby_index: lobbyIndex },
    }).then((r) => r.json());
  },

  /** The other direction: everyone in the team voices goes back to the general one. */
  voiceReturn(workspaceId: number, gameId: number, lobbyIndex: number | null): Promise<MixVoiceReport> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/voice/return`, {
      skipWorkspace: true,
      method: "POST",
      body: { lobby_index: lobbyIndex },
    }).then((r) => r.json());
  },

  /**
   * Rewrites this lobby's posted lineup card in place, with the matchup
   * rasterised in the browser exactly like `postToDiscord`; `null` falls back
   * to the server's text embed.
   */
  async refreshLineup(
    workspaceId: number,
    gameId: number,
    lobbyIndex: number,
    image: Blob | null = null,
  ): Promise<{ status: "queued" | "nothing_to_update" }> {
    const response = await apiFetch(
      `/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/discord/lineup`,
      {
        skipWorkspace: true,
        method: "PUT",
        body: { lobby_index: lobbyIndex, image_b64: image ? await blobToBase64(image) : null },
      },
    );
    return response.json();
  },
};
