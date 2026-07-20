import { cache } from "react";

import { isNotFoundError } from "@/lib/api-error";
import tournamentService from "@/services/tournament.service";
import workspaceService from "@/services/workspace.service";
import type { Tournament } from "@/types/tournament.types";
import type { Workspace } from "@/types/workspace.types";

export type TournamentOverviewState =
  { kind: "success"; overview: Tournament } | { kind: "not-found" } | { kind: "error" };

const CANONICAL_TOURNAMENT_ID = /^[1-9]\d*$/;
// A `/tournaments/<id>` route (with or without a trailing sub-path), used to
// resolve the owning workspace for the server-side theme seed from the request
// pathname the middleware forwards.
const TOURNAMENT_ROUTE = /^\/tournaments\/([1-9]\d*)(?:\/|$)/;

export function parseCanonicalTournamentId(rawTournamentId: string): number | null {
  if (!CANONICAL_TOURNAMENT_ID.test(rawTournamentId)) {
    return null;
  }

  const tournamentId = Number(rawTournamentId);
  return Number.isSafeInteger(tournamentId) ? tournamentId : null;
}

export function tournamentIdFromPathname(pathname: string): number | null {
  const match = TOURNAMENT_ROUTE.exec(pathname);
  return match ? parseCanonicalTournamentId(match[1]) : null;
}

async function loadTournamentOverviewState(tournamentId: number): Promise<TournamentOverviewState> {
  if (!Number.isSafeInteger(tournamentId) || tournamentId <= 0) {
    return { kind: "not-found" };
  }

  try {
    const overview = await tournamentService.getPublicOverview(tournamentId);
    return { kind: "success", overview };
  } catch (error) {
    return isNotFoundError(error) ? { kind: "not-found" } : { kind: "error" };
  }
}

export const getTournamentOverviewState = cache(async (tournamentId: number) => {
  return loadTournamentOverviewState(tournamentId);
});

/**
 * The tournament's owning workspace, used to seed the site theme with that
 * workspace's brand (a tournament may belong to a workspace other than the one
 * the viewer has selected). Cached per request so the `(site)` layout SSR seed
 * and the tournament layout share a single lookup. Degrades to `null` on any
 * failure so theming simply falls back to the viewer's palette.
 */
export const getTournamentOwnerWorkspace = cache(
  async (tournamentId: number): Promise<Workspace | null> => {
    const state = await getTournamentOverviewState(tournamentId);
    if (state.kind !== "success") return null;
    try {
      return await workspaceService.getById(state.overview.workspace_id);
    } catch {
      return null;
    }
  },
);
