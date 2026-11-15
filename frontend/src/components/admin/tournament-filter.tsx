import type { FilterOption, FilterValue } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import { RowGameMark } from "@/components/workspace/game-column";

/**
 * The `?tournament=` query param shared by every admin browser that can be
 * scoped to one tournament (encounters, standings, parsed maps, reports,
 * teams, people).
 *
 * The chip that writes it is `kit/FilterBar`; this file is the name of the
 * param, its parser and the chip's game-aware options, so the chip, the table's
 * filter engine and the page's own query all agree on one spelling.
 */

export const TOURNAMENT_QUERY_PARAM = "tournament";

export function parseTournamentQueryParam(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

/**
 * The tournament chip's options: the filtered game's tournaments, or — with no game filtered — every tournament of
 * the community, each led by its game's mark.
 */
export function tournamentOptions(
  tournaments: readonly { id: number; name: string; discipline: string }[],
  game: string | null
): FilterOption[] {
  return tournaments
    .filter((tournament) => game === null || tournament.discipline === game)
    .map((tournament) => ({
      value: String(tournament.id),
      label: tournament.name,
      icon: game === null ? <RowGameMark code={tournament.discipline} /> : undefined
    }));
}

/**
 * What a game-chip pick strands of the chosen tournament: the tournament, its stage and group when it is another
 * game's. Clearing the game, or picking the tournament's own, keeps them.
 */
export function strandedTournamentParams(
  tournamentGame: string | undefined,
  next: FilterValue | null
): readonly string[] {
  return tournamentGame && next && next !== tournamentGame ? [TOURNAMENT_QUERY_PARAM, "stage", "group"] : [];
}
