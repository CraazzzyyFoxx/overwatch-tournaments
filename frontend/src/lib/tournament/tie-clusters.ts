/**
 * The tie clusters sitting on both sides of `boundary`.
 *
 * For those teams the assigned order — not anything they earned on the pitch —
 * decides which side of the line they land on, which is the one thing a
 * standings table has to say out loud. Soft signal: callers mark the rows and
 * block nothing.
 *
 * Takes the two columns it reads, not a `Standings`: an FFA lobby row carries
 * the same position/tie_group pair and marks its cut line the same way. It
 * lives here rather than beside one of those tables so neither has to import
 * the other — `components/ffa` reaching into `StandingsTable` dragged that
 * table's whole message namespace into every zone that renders a lobby.
 */
export function straddlingTieGroups(
  rows: ReadonlyArray<{ position: number; tie_group: number | null }>,
  boundary: number
): Set<number> {
  const groups = new Set<number>();
  for (const row of rows) {
    if (row.tie_group == null || row.position > boundary) continue;
    if (rows.some((other) => other.tie_group === row.tie_group && other.position > boundary)) {
      groups.add(row.tie_group);
    }
  }
  return groups;
}
