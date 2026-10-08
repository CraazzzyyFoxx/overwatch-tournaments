import { cache } from "react";

import { getTournamentStatusMeta, isTournamentStatusActive } from "@/lib/tournament/status";
import tournamentService from "@/services/tournament.service";
import type { Tournament } from "@/types/tournament.types";

/**
 * Reads shared by several blocks of the community page. `cache()` so the hero,
 * the "now" block and the about section ask for the same tournament once per
 * request instead of three times.
 */

/**
 * The community's one current tournament: what is being played, else what is
 * open for entries. Everything else (announced, drafting, checking in) is not
 * something a visitor can act on, so the page falls back to the last finished
 * tournament instead.
 *
 * `getActive` is cross-workspace on purpose — on the platform host the ambient
 * workspace is whichever community the viewer last looked at, not this one.
 */
export const getCommunityTournament = cache(
  async (workspaceId: number): Promise<Tournament | null> => {
    const page = await tournamentService.getActive();
    const mine = page.results.filter(
      (tournament) =>
        tournament.workspace_id === workspaceId &&
        !tournament.is_hidden &&
        isTournamentStatusActive(tournament.status)
    );
    return (
      mine.find((tournament) => getTournamentStatusMeta(tournament.status).variant === "live") ??
      mine.find((tournament) => tournament.status === "registration") ??
      null
    );
  }
);

/** The year the community ran its first tournament ("С 2019 года"). */
export const getFirstTournamentYear = cache(
  async (workspaceId: number): Promise<number | null> => {
    const page = await tournamentService.listTournaments({
      workspaceId,
      sort: "start_date",
      order: "asc",
      perPage: 1
    });
    const first = page.results[0];
    return first ? new Date(first.start_date).getUTCFullYear() : null;
  }
);
