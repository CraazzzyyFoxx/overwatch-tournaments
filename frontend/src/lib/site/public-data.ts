import { cache } from "react";

import tournamentService from "@/services/tournament.service";
import workspaceService from "@/services/workspace.service";

// The platform landings read these lists from several sections, each behind
// its own Suspense boundary: on `/` the "now on the platform" block, the
// catalogue and the totals; on `/get-workspace` the community row and the
// domains walk-through. `cache()` collapses them to one request per render.
export const getPublicWorkspaces = cache(() => workspaceService.getAll("public"));
export const getActiveTournaments = cache(() =>
  tournamentService.getActive({ skipWorkspace: true })
);
