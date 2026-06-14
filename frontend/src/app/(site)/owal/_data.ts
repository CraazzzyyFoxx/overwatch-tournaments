import tournamentService from "@/services/tournament.service";
import { OwalStack, OwalStandings } from "@/types/tournament.types";
import { EMPTY_OWAL_STACKS, EMPTY_OWAL_STANDINGS } from "./_constants";
import { resolveSeason } from "./_utils";

export type OwalPageSearchParams = {
  season?: string;
};

export type OwalPageData = {
  seasons: string[];
  selectedSeason: string | undefined;
  standings: OwalStandings;
  stacks: OwalStack[];
};

export const getOwalPageData = async (
  searchParamsPromise: Promise<OwalPageSearchParams>
): Promise<OwalPageData> => {
  const [searchParams, seasons] = await Promise.all([
    searchParamsPromise,
    tournamentService.getOwalSeasons()
  ]);

  const selectedSeason = resolveSeason(searchParams.season, seasons);

  if (!selectedSeason) {
    return {
      seasons,
      selectedSeason,
      standings: EMPTY_OWAL_STANDINGS,
      stacks: EMPTY_OWAL_STACKS
    };
  }

  const [standings, stacks] = await Promise.all([
    tournamentService.getOwalStandings(selectedSeason),
    tournamentService.getOwalStacks(selectedSeason)
  ]);

  return {
    seasons,
    selectedSeason,
    standings,
    stacks
  };
};
