import { apiFetch } from "@/lib/api-fetch";
import { blobToBase64 } from "@/lib/image-capture";
import type { RosterShape, RosterSlotMap } from "@/lib/roster-shape";

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
 * What the mix engine (`mix_balancer`) actually reads out of a mix's stored
 * solver overrides. Anything else the server accepts tunes the tournament GA
 * and changes nothing about a two-team mix, so it stays unnamed but is kept
 * on round-trip by the index signature.
 */
export type MixBalancerConfig = {
  /**
   * Trade-off between rank balance and role comfort: `0` splits ranks as
   * evenly as possible, `1` maximises players seated on a preferred role,
   * `0.5` (the default) is the engine's own weighting.
   */
  mix_comfort_tilt?: number | null;
  /**
   * Per-role importance for the role-line balance term, keyed by roster slot
   * code. A role left out weighs `1`.
   */
  mix_role_weights?: Record<string, number> | null;
  [key: string]: unknown;
};

/**
 * The mix's own settings. Each one is a stored fact with its own type -- there
 * is no config blob to parse, and no key that can silently mean two things.
 */
export type CustomGameSettings = {
  points_per_win: number | null;
  /** Host overrides keyed by 0-based team index. Absent index = computed default. */
  team_names: Record<string, string>;
  /** The mix's own roster shape override; `null` inherits the workspace default. */
  role_mask: RosterSlotMap | null;
  /**
   * Validated solver overrides; `null` means the engine defaults. The blob is
   * validated against the full `ConfigOverrides` schema server-side, but only
   * the two `mix_*` keys reach the mix engine -- the rest tune the tournament
   * GA and are no-ops for a two-team mix.
   */
  balancer_config: MixBalancerConfig | null;
  /**
   * This mix's own channel override, or `null` when it follows the workspace.
   * Only a workspace admin can set it (`custom.set_discord_channel`).
   * A snowflake as a string: Discord ids exceed JS safe integers, so the wire
   * format is decimal text on the way out and on the way in.
   */
  discord_channel_id: string | null;
  /**
   * The workspace-wide mix channel, where `postToDiscord` sends the matchup
   * unless this mix overrides it. Read `discord_channel_id ?? this` for the
   * channel a post actually lands in -- the same fallback the server applies.
   */
  workspace_discord_channel_id: string | null;
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
  /** The solver's own document for the last balance, or `null` before one. */
  balance_result: unknown;
  created_at: string | null;
  /**
   * The map the next match is played on -- rolled or picked by a host, seen by
   * every viewer, stamped on the next recorded match and cleared by it. Only
   * the id: name, mode and thumbnail resolve against the loaded catalogue.
   */
  next_map_id: number | null;
  /**
   * The mix's resolved team composition -- own `settings.role_mask` override,
   * else the workspace default, else the built-in Overwatch 5v5 shape.
   */
  roster_shape: RosterShape | null;
  /** How many matches this mix has recorded -- the list's activity read, without loading the history. */
  matches_count: number;
  /** When the newest match was recorded, or `null` while none has been. */
  last_match_at: string | null;
  players?: CustomGamePlayer[];
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
  by_role: Partial<Record<"tank" | "dps" | "support", MixRoleTally>>;
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
  matches: (workspaceId: number, gameId: number) => ["custom-games", workspaceId, gameId, "matches"] as const,
  rotation: (workspaceId: number, gameId: number) => ["custom-games", workspaceId, gameId, "rotation"] as const,
  stats: (workspaceId: number, since: string | null) =>
    ["custom-games", workspaceId, "stats", since ?? "all"] as const,
};

export const customGameService = {
  list(workspaceId: number): Promise<CustomGame[]> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games`).then((r) => r.json());
  },

  /**
   * Starts empty: the lineup is built explicitly from the workspace roster.
   * `cloneFromGameId` instead copies a previous mix's lineup and settings --
   * everyone lands in the pool, and no match history comes with it.
   */
  create(workspaceId: number, name: string, cloneFromGameId: number | null = null): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games`, {
      method: "POST",
      body: {
        name,
        member_ids: [],
        ...(cloneFromGameId != null ? { clone_from_game_id: cloneFromGameId } : {}),
      },
    }).then((r) => r.json());
  },

  get(workspaceId: number, gameId: number): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}`).then((r) => r.json());
  },

  updateRoster(workspaceId: number, gameId: number, memberIds: number[]): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/roster`, {
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
      `/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/players/${workspaceMemberId}`,
      { method: "PUT", body: patch },
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
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/players`, {
      method: "PUT",
      body: { players },
    }).then((r) => r.json());
  },

  balance(workspaceId: number, gameId: number): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/balance`, {
      method: "POST",
    }).then((r) => r.json());
  },

  /**
   * Snapshots one played match into the permanent casual-match log — team
   * rosters and who won. Repeatable: a mix can record many before its host
   * calls `close`. `variantIndex` is whichever balance option is on screen;
   * the map is the mix's `next_map_id`, consumed server-side.
   */
  recordOutcome(
    workspaceId: number,
    gameId: number,
    outcome: CustomGameOutcome,
    variantIndex: number,
  ): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/outcome`, {
      method: "POST",
      body: { outcome, variant_index: variantIndex },
    }).then((r) => r.json());
  },

  /** Every match this mix has recorded, newest first. */
  listMatches(workspaceId: number, gameId: number): Promise<CustomGameMatch[]> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/matches`).then((r) => r.json());
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
      `/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/matches/${matchId}`,
      { method: "DELETE" },
    ).then((r) => r.json());
  },

  /**
   * Who is owed the next seat and who should rest, ranked from this mix's own
   * map history and split at the seat count `balance` would fill right now
   * (see `mix_rotation.recommend_rotation`). Read-only, feeds the lineup as a
   * hint -- it writes nothing on its own.
   */
  rotation(workspaceId: number, gameId: number): Promise<RotationRecommendation[]> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/rotation`).then((r) =>
      r.json(),
    );
  },

  /**
   * Every member's win/loss record across this workspace's mixes, read from
   * the permanent match log rather than from any one mix. `since` (ISO) counts
   * only matches recorded from then on; `null` counts all time.
   */
  stats(workspaceId: number, since: string | null = null): Promise<MixStatsResponse> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/stats`, {
      // `apiFetch` drops a null query value, so all time sends no `since` at all.
      query: { since },
    }).then((r) => r.json());
  },

  /** Ends the mix. Matches already recorded stay recorded; this only stops further writes. */
  close(workspaceId: number, gameId: number): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/close`, {
      method: "POST",
    }).then((r) => r.json());
  },

  /**
   * Permanently deletes the mix and every match it recorded. Workspace admin
   * only -- unlike `close` (a host-triggered status flip) this is irreversible.
   */
  hardDelete(workspaceId: number, gameId: number): Promise<void> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}`, {
      method: "DELETE",
    }).then(() => undefined);
  },

  /**
   * Patch semantics: an index left out of ``teamNames`` keeps its current
   * name; an empty string clears that team's override back to the computed
   * default (``Team N``).
   */
  setTeamNames(workspaceId: number, gameId: number, teamNames: Record<string, string>): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/team-names`, {
      method: "PUT",
      body: { team_names: teamNames },
    }).then((r) => r.json());
  },

  /**
   * Patch the mix's own roster-shape override, or clear it (`null`) to inherit
   * the workspace default -- the same override/inherit split
   * `RosterShapeEditor` already offers for a tournament's `roster_slots_json`.
   */
  setRoleMask(workspaceId: number, gameId: number, roleMask: RosterSlotMap | null): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/role-mask`, {
      method: "PUT",
      body: { role_mask: roleMask },
    }).then((r) => r.json());
  },

  /**
   * Replaces the mix's solver overrides, or clears them (`null`) back to the
   * engine defaults. Validated server-side against `ConfigOverrides`, so an
   * out-of-range weight 422s here instead of landing in the next balance run.
   */
  setBalancerConfig(
    workspaceId: number,
    gameId: number,
    balancerConfig: MixBalancerConfig | null,
  ): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/balancer-config`, {
      method: "PUT",
      body: { balancer_config: balancerConfig },
    }).then((r) => r.json());
  },

  /**
   * The host's rank-adjustment-per-win knob: recording a win/loss then bumps
   * the winning team's author-book rank by this many points and the losing
   * team's down by the same, per player and role. `null`/`0` disables it.
   */
  setPointsPerWin(workspaceId: number, gameId: number, pointsPerWin: number | null): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/points-per-win`, {
      method: "PUT",
      body: { points_per_win: pointsPerWin },
    }).then((r) => r.json());
  },

  /**
   * Names the map the next match is played on, or clears it (`null`). The roll
   * itself happens client-side (`rollNextMap`); this stores the verdict so
   * co-hosts and viewers see the same map and `recordOutcome` stamps it.
   */
  setNextMap(workspaceId: number, gameId: number, mapId: number | null): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/next-map`, {
      method: "PUT",
      body: { map_id: mapId },
    }).then((r) => r.json());
  },

  /**
   * Hands primary ownership to another workspace member. Any current writer
   * -- the host or a co-host -- may call this; it 403s the caller's very
   * next write here unless they are also a co-host, and opens every write
   * (roster, balance, outcomes, settings) to the new host.
   */
  transferHost(workspaceId: number, gameId: number, newHostUserId: number): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/host`, {
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
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/co-hosts`, {
      method: "POST",
      body: { co_host_user_id: coHostUserId },
    }).then((r) => r.json());
  },

  /** Revokes a co-host's write access, including a co-host removing themselves. */
  removeCoHost(workspaceId: number, gameId: number, coHostUserId: number): Promise<CustomGame> {
    return apiFetch(
      `/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/co-hosts/${coHostUserId}`,
      { method: "DELETE" },
    ).then((r) => r.json());
  },

  /**
   * Swap two seated players between teams, same role only -- a same-role swap
   * can never break a team's role quota, so it needs no eligibility check
   * beyond "both exist and share a role". `variantIndex` edits whichever
   * balance option is on screen, not always the first.
   */
  swapSeats(
    workspaceId: number,
    gameId: number,
    variantIndex: number,
    firstUuid: string,
    secondUuid: string,
  ): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/teams/swap`, {
      method: "POST",
      body: { variant_index: variantIndex, first_uuid: firstUuid, second_uuid: secondUuid },
    }).then((r) => r.json());
  },

  /**
   * Names the channel `postToDiscord` posts the matchup to, or clears it
   * (`null`). The id travels as a string: a Discord snowflake does not survive
   * a round trip through a JS number.
   */
  setDiscordChannel(workspaceId: number, gameId: number, channelId: string | null): Promise<CustomGame> {
    return apiFetch(`/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/discord-channel`, {
      method: "PUT",
      body: { channel_id: channelId },
    }).then((r) => r.json());
  },

  /**
   * Posts the current matchup -- teams and the next map -- to the mix's Discord
   * channel. Fire-and-forget: the response only says the message was queued for
   * the bot, so a delivery that fails afterwards surfaces in the bot's logs,
   * not here. `variantIndex` is whichever balance option is on screen.
   *
   * `image` is that matchup rasterised in the browser; it is what the bot
   * attaches. Passing `null` (a capture that failed, or a caller with no node
   * to capture) posts the server's text embed instead.
   */
  async postToDiscord(
    workspaceId: number,
    gameId: number,
    variantIndex: number,
    image: Blob | null = null,
  ): Promise<{ status: "queued"; channel_id: string }> {
    const response = await apiFetch(
      `/api/balancer/workspaces/${workspaceId}/custom-games/${gameId}/discord/post`,
      {
        method: "POST",
        body: { variant_index: variantIndex, image_b64: image ? await blobToBase64(image) : null },
      },
    );
    return response.json();
  },
};
