export const resolveSeason = (requestedSeason: string | undefined, seasons: string[]) => {
  if (!requestedSeason || seasons.length === 0) {
    return seasons[0];
  }

  const seasonsSet = new Set(seasons);
  return seasonsSet.has(requestedSeason) ? requestedSeason : seasons[0];
};
