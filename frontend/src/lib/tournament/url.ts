/**
 * Builds the public tournament URL from its slug (`/tournaments/{slug}`),
 * never the bare id. `path` appends a sub-route/query, e.g. `"/bracket"` or
 * `"/bracket?stage=3"`.
 *
 * Accepts a plain numeric id as a fallback for the few call sites that only
 * carry a `tournament_id` foreign key (no nested tournament object) — that
 * still resolves correctly server-side (legacy numeric ids keep working),
 * just without the readable slug. Prefer passing the full tournament once its
 * slug is available on that read.
 */
export function tournamentHref(tournament: { slug: string } | number, path: string = ""): string {
  const ref = typeof tournament === "number" ? tournament : tournament.slug;
  return `/tournaments/${ref}${path}`;
}
