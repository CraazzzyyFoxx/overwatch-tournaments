/**
 * Mapping a published version's divisions onto the draft's, by rank overlap.
 *
 * Every tournament keeps the grid version it was played on, so the workspace
 * needs a translation from each still-read version's tiers to the new ones.
 * Players are stored on the grid's own rank scale, so overlap is measured
 * there — the same rule the backend's automap applies — and "which division
 * does this old one become" is the draft division sharing most of its range.
 * Only a tie needs a person (SPLIT); every other row is AUTO, and any row may
 * be overridden, because across a scale change overlap stops meaning anything.
 *
 * Pure: takes tiers and bands, returns rows and rules.
 */

import type { DivisionGridMappingRule, DivisionTier } from "@/types/workspace.types";

import { bandsFromTiers, LADDER, type Band } from "./draftReducer";

export interface MappingCandidate {
  band: Band;
  /** Rank values shared with the source division. */
  overlap: number;
  /** `overlap` as a share of the source division's range, `0 … 1`. */
  weight: number;
}

export interface MappingRow {
  /** The source tier as a band, carrying the tier id the rules key on. */
  source: Band;
  /** Overlapping draft divisions, most overlap first; ties broken by position. */
  candidates: MappingCandidate[];
  /** `split` when the leading candidates tie, so the primary has to be chosen. */
  kind: "auto" | "split";
  /** Share of the source range covered by the leading candidate. */
  coverage: number;
}

const OW_FLOORS = new Set(LADDER.map((rank) => rank.rank_min));
const LADDER_BOTTOM = LADDER[LADDER.length - 1].rank_min;

/**
 * A finite top for the open-ended divisions, so they get a comparable width.
 * When both grids sit on the OW ladder that is where the ladder physically ends
 * (4999), which makes the overlap exactly the ladder's rank count; elsewhere it
 * is one step of the finest division above the highest floor.
 */
function openCeiling(lists: Band[][]): number {
  // Only a bottom division may start under Bronze 5 and still be a ladder band.
  const onLadder = lists.every((list) =>
    list.every(
      (band, index) =>
        OW_FLOORS.has(band.rankMin) || (index === list.length - 1 && band.rankMin <= LADDER_BOTTOM)
    )
  );
  if (onLadder) return LADDER[0].rank_min + (LADDER[0].rank_min - LADDER[1].rank_min) - 1;
  const all = lists.flat();
  const widths = all.flatMap((band) =>
    band.rankMax !== null && band.rankMax >= band.rankMin ? [band.rankMax - band.rankMin + 1] : []
  );
  const step = widths.length > 0 ? Math.min(...widths) : 1;
  return Math.max(...all.map((band) => band.rankMin)) + step - 1;
}

export function autoMap(sourceTiers: DivisionTier[], bands: Band[]): MappingRow[] {
  const sources = bandsFromTiers(sourceTiers);
  if (bands.length === 0) {
    return sources.map((source) => ({ source, candidates: [], kind: "split", coverage: 0 }));
  }
  const ceiling = openCeiling([sources, bands]);
  // Below its bottom floor a grid still resolves into its bottom division.
  const floor = Math.min(...[...sources, ...bands].map((band) => band.rankMin));
  const span = (band: Band, list: Band[]): [number, number] => [
    band === list[list.length - 1] ? floor : band.rankMin,
    band.rankMax ?? ceiling
  ];

  return sources.map((source) => {
    const [low, high] = span(source, sources);
    const size = Math.max(1, high - low + 1);
    const candidates = bands
      .map((band) => {
        const [bandLow, bandHigh] = span(band, bands);
        const overlap = Math.max(0, Math.min(high, bandHigh) - Math.max(low, bandLow) + 1);
        return { band, overlap, weight: overlap / size };
      })
      .filter((candidate) => candidate.overlap > 0)
      .sort((left, right) => right.overlap - left.overlap || left.band.number - right.band.number);

    const leader = candidates[0];
    const tied = candidates.length > 1 && candidates[1].overlap === leader.overlap;
    return {
      source,
      candidates,
      kind: !leader || tied ? ("split" as const) : ("auto" as const),
      coverage: leader ? leader.weight : 0
    };
  });
}

/**
 * The primary target for a row: the user's (or the stored) choice while it
 * still names a draft division, else the leading candidate of an AUTO row.
 */
export function primaryTarget(
  row: MappingRow,
  chosen: Record<number, number | undefined>,
  bands: Band[]
): Band | null {
  const pickedId = row.source.id === undefined ? undefined : chosen[row.source.id];
  const picked = pickedId === undefined ? undefined : bands.find((band) => band.id === pickedId);
  if (picked) return picked;
  return row.kind === "auto" ? (row.candidates[0]?.band ?? null) : null;
}

/** Rows still waiting on a decision — the tab badge, and the publish blocker. */
export function unresolvedRows(
  rows: MappingRow[],
  chosen: Record<number, number | undefined>,
  bands: Band[]
): MappingRow[] {
  return rows.filter((row) => primaryTarget(row, chosen, bands) === null);
}

const round6 = (value: number) => Math.round(value * 1e6) / 1e6;

/**
 * The rows as mapping rules, in the shape the backend validates: per source
 * tier the weights sum to 1 and exactly one rule is primary. `weight` records
 * how the old range divides over the overlapping divisions; `is_primary` is
 * where a player from it lands. A primary chosen outside the overlap is the
 * whole mapping for its row. Rows without a primary are left out, which is
 * what keeps the mapping incomplete until they are resolved.
 */
export function mappingRules(
  rows: MappingRow[],
  chosen: Record<number, number | undefined>,
  bands: Band[]
): DivisionGridMappingRule[] {
  const rules: DivisionGridMappingRule[] = [];
  for (const row of rows) {
    const sourceTierId = row.source.id;
    const primary = primaryTarget(row, chosen, bands);
    if (sourceTierId === undefined || primary?.id === undefined) continue;

    const overlapping = row.candidates.filter((candidate) => candidate.band.id !== undefined);
    const total = overlapping.reduce((sum, candidate) => sum + candidate.overlap, 0);
    const secondary = overlapping
      .filter((candidate) => candidate.band.id !== primary.id)
      .map((candidate) => ({
        source_tier_id: sourceTierId,
        target_tier_id: candidate.band.id!,
        weight: round6(candidate.overlap / total),
        is_primary: false
      }))
      .filter((rule) => rule.weight > 0);
    const primaryOverlaps = overlapping.some((candidate) => candidate.band.id === primary.id);

    rules.push({
      source_tier_id: sourceTierId,
      target_tier_id: primary.id,
      weight: primaryOverlaps
        ? round6(1 - secondary.reduce((sum, rule) => sum + rule.weight, 0))
        : 1,
      is_primary: true
    });
    if (primaryOverlaps) rules.push(...secondary);
  }
  return rules;
}
