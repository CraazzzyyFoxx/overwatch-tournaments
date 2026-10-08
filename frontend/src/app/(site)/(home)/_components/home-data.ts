import { cache } from "react";

import tournamentService from "@/services/tournament.service";
import workspaceService from "@/services/workspace.service";

// Both the "now on the platform" block and the catalogue need these two lists,
// and each section fetches on its own behind its own Suspense boundary.
// `cache()` collapses them to one request per render instead of two.
export const getPublicWorkspaces = cache(() => workspaceService.getAll("public"));
export const getActiveTournaments = cache(() =>
  tournamentService.getActive({ skipWorkspace: true })
);
