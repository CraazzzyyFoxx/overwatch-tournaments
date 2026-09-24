/**
 * The `?tournament=` query param shared by every admin browser that can be
 * scoped to one tournament (encounters, standings, parsed maps, reports,
 * teams, people).
 *
 * The chip that writes it is `kit/FilterBar`; this file is only the name
 * of the param and its parser, so the chip, the table's filter engine and the
 * page's own query all agree on one spelling.
 */

export const TOURNAMENT_QUERY_PARAM = "tournament";

export function parseTournamentQueryParam(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}
