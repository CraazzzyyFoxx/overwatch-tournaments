import { apiFetch } from "@/lib/api/fetch";
import type { PaginatedResponse } from "@/types/pagination.types";

/**
 * One workspace member as the roster shows them.
 *
 * Two rank dictionaries, never merged: `ranks` is the workspace canon — the
 * shared fallback — and `author_ranks` is one author's own book, the caller's
 * unless a different `authorUserId` was asked for. Keeping them apart is what
 * lets a row say whether a number is its own or inherited; a single merged dict
 * cannot answer that.
 */
export type RosterMember = {
  member_id: number;
  player_id: number;
  /**
   * The player's linked login identity (`auth.user.id`), or `null` if they
   * have never signed in. A mix's `host_user_id`/`co_host_user_ids` live in
   * this id space, not `player_id` -- a member with no linked account can be
   * ranked and rostered, but can never be picked as a host or co-host.
   */
  auth_user_id: number | null;
  battle_tag: string | null;
  display_name: string | null;
  ranks: Record<string, number>;
  author_ranks: Record<string, number>;
};

/** The two chip counts the add-players dialog needs before either is clicked. */
export type RosterSummary = {
  total: number;
  author_total: number;
};

/**
 * One account that has personally rank-corrected somebody in this workspace --
 * the add-players dialog's per-author filter chips beyond "Everyone"/"My
 * ranks". `count` is how many distinct members they have ranked, busiest
 * author first.
 */
export type RosterAuthor = {
  user_id: number;
  display_name: string | null;
  count: number;
};

/** Which rank layer a write lands in. `author` is always the caller's own book. */
export type RankScope = "workspace" | "author";

export type WorkspacePlayerListParams = {
  page?: number;
  perPage?: number;
  query?: string;
  /** Whose book to return as `author_ranks`; omitted means the caller's. */
  authorUserId?: number;
  /** The "My ranks" shortcut: only members that author has personally corrected. */
  authorOnly?: boolean;
};

export const workspacePlayerKeys = {
  all: (workspaceId: number) => ["workspace-players", workspaceId] as const,
  list: (workspaceId: number, params: WorkspacePlayerListParams = {}) =>
    [
      ...workspacePlayerKeys.all(workspaceId),
      params.page ?? 1,
      params.perPage ?? 30,
      params.query ?? "",
      params.authorUserId ?? 0,
      params.authorOnly ?? false,
    ] as const,
  summary: (workspaceId: number, authorUserId?: number) =>
    [...workspacePlayerKeys.all(workspaceId), "summary", authorUserId ?? 0] as const,
  authors: (workspaceId: number) => [...workspacePlayerKeys.all(workspaceId), "authors"] as const,
};

export const workspacePlayerService = {
  list(workspaceId: number, params: WorkspacePlayerListParams = {}): Promise<PaginatedResponse<RosterMember>> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/players`, {
      query: {
        page: params.page ?? 1,
        per_page: params.perPage ?? 30,
        query: params.query ?? "",
        ...(params.authorUserId == null ? {} : { author_user_id: params.authorUserId }),
        ...(params.authorOnly ? { author_only: 1 } : {}),
      },
    }).then((r) => r.json());
  },

  summary(workspaceId: number, authorUserId?: number): Promise<RosterSummary> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/players/summary`, {
      query: authorUserId == null ? {} : { author_user_id: authorUserId },
    }).then((r) => r.json());
  },

  /** Every author who has ever set a rank here, busiest first. */
  listAuthors(workspaceId: number): Promise<{ authors: RosterAuthor[] }> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/players/authors`).then((r) => r.json());
  },

  upsert(workspaceId: number, battleTag: string, displayName?: string): Promise<RosterMember> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/players`, {
      method: "POST",
      body: { battle_tag: battleTag, display_name: displayName || undefined },
    }).then((r) => r.json());
  },

  /**
   * Writes one rank layer for a member.
   *
   * `scope: "author"` is the caller's own book and nobody else's — the endpoint
   * takes no author id, so there is no way to edit another organiser's ranks
   * even though any member may read them. `scope: "workspace"` writes the shared
   * canon, which every author inherits until they set their own.
   *
   * `clear` deletes those roles from the layer instead of zeroing them, so an
   * author rank falls back to canon. An omitted role is left alone, which is
   * what lets one picker save without disturbing the other two.
   */
  setRanks(
    workspaceId: number,
    memberId: number,
    input: { scope?: RankScope; ranks: Record<string, number>; clear?: string[] },
  ): Promise<{ ranks: Record<string, number> }> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/players/${memberId}/ranks`, {
      method: "PUT",
      body: {
        scope: input.scope ?? "workspace",
        ranks: input.ranks,
        clear: input.clear ?? [],
      },
    }).then((r) => r.json());
  },
};
