import { cache } from "react";

import statisticsService from "@/services/statistics.service";
import tournamentService from "@/services/tournament.service";
import workspaceService from "@/services/workspace.service";
import type { WorkspaceListItem } from "@/types/workspace.types";

// The platform landings read these lists from several sections, each behind
// its own Suspense boundary: on `/` the "now on the platform" block, the
// catalogue and the totals; on `/get-workspace` the community row and the
// domains walk-through. `cache()` collapses them to one request per render.
export const getPublicWorkspaces = cache(() => workspaceService.getAll("public"));
export const getActiveTournaments = cache(() =>
  tournamentService.getActive({ skipWorkspace: true })
);

/** A public community with its own all-time totals; `null` where its statistics read failed. */
export interface PublicCommunity {
  workspace: WorkspaceListItem;
  tournaments: number | null;
  players: number | null;
}

/**
 * Every public community with its tournaments and players: the home's
 * catalogue and the organizer page's community row. Throws when the directory
 * read fails; one community's failed totals only leave its own figures out.
 */
export const getPublicCommunities = cache(async (): Promise<PublicCommunity[]> => {
  const workspaces = await getPublicWorkspaces();
  return Promise.all(
    workspaces.map(async (workspace) => {
      // ponytail: one statistics read per community (edge-cached, 60s) because
      // the directory read has no per-community totals. Fine for a few dozen
      // communities; past that, put the totals on the directory read.
      const totals = await statisticsService
        .getOverallStatistics({ workspaceId: workspace.id })
        .catch(() => null);
      return { workspace, tournaments: totals?.tournaments ?? null, players: totals?.players ?? null };
    })
  );
});
