/**
 * Mapping a published version's divisions onto the draft's, by rank overlap.
 *
 * Every tournament keeps the grid version it was played on, so the workspace
 * needs a translation from each still-read version's tiers to the new ones.
 * Players are stored on the grid's own rank scale, so overlap is measured
 * there — the same rule the backend's automap applies: an old division maps
 * onto the draft divisions it overlaps, and its players land in the one
 * sharing most of its range. Only a tie needs a person (SPLIT); every other
 * row is AUTO. Any row may be overridden with a range of draft divisions and
 * the one players land in, because across a scale change overlap stops
 * meaning anything.
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
 * A decision for one source division, keyed by source tier id: the draft
 * divisions its players spread over — the range is the hull of `targets` in
 * draft order — and the one they land in. `null` asks for the automatic
 * mapping even where a stored one says otherwise.
 */
export interface MappingChoice {
  targets: number[];
  primary: number;
}

export type MappingChoices = Record<number, MappingChoice | null | undefined>;

export interface MappingTarget {
  /** Consecutive draft divisions the source's players spread over, top first. */
  range: Band[];
  /** Where a player of the source division lands — the rule marked primary. */
  primary: Band;
  /** Share of the source's players per division of `range`; sums to 1. */
  weights: number[];
  /** Shares follow rank overlap; otherwise the range is split evenly. */
  byOverlap: boolean;
  /** Chosen rather than the automatic mapping. */
  manual: boolean;
}

/**
 * How the source's players divide over `range`: by rank overlap while every
 * division of it overlaps the source, else evenly — across a scale change, or
 * past the overlap, overlap no longer says where anyone goes.
 */
function spread(row: MappingRow, range: Band[]): Pick<MappingTarget, "weights" | "byOverlap"> {
  const overlaps = range.map(
    (band) => row.candidates.find((candidate) => candidate.band.slug === band.slug)?.overlap ?? 0
  );
  const byOverlap = overlaps.every((overlap) => overlap > 0);
  const total = byOverlap ? overlaps.reduce((sum, overlap) => sum + overlap, 0) : range.length;
  return { weights: overlaps.map((overlap) => (byOverlap ? overlap : 1) / total), byOverlap };
}

/** The overlapping divisions, top first — the range an AUTO row maps onto, and a SPLIT row's proposal. */
export function overlapRange(row: MappingRow): Band[] {
  return row.candidates
    .map((candidate) => candidate.band)
    .sort((left, right) => left.number - right.number);
}

/**
 * Where a row's players go: the user's (or the stored) choice while its
 * primary still names a draft division, else the automatic mapping of an AUTO
 * row, else `null` — a SPLIT row nobody has decided yet.
 */
export function resolveTarget(
  row: MappingRow,
  choices: MappingChoices,
  bands: Band[]
): MappingTarget | null {
  const leader = row.candidates[0];
  const overlapping = overlapRange(row);
  const automatic: MappingTarget | null =
    row.kind === "auto" && leader
      ? { range: overlapping, primary: leader.band, ...spread(row, overlapping), manual: false }
      : null;

  const choice = row.source.id === undefined ? undefined : choices[row.source.id];
  const primaryIndex = choice ? bands.findIndex((band) => band.id === choice.primary) : -1;
  // No choice, or one whose landing division was merged away since.
  if (!choice || primaryIndex === -1) return automatic;

  const indices = [
    primaryIndex,
    ...choice.targets
      .map((id) => bands.findIndex((band) => band.id === id))
      .filter((index) => index !== -1)
  ];
  const range = bands.slice(Math.min(...indices), Math.max(...indices) + 1);
  const primary = bands[primaryIndex];
  const same =
    automatic !== null &&
    automatic.primary.slug === primary.slug &&
    automatic.range.length === range.length &&
    automatic.range[0].slug === range[0].slug;
  return { range, primary, ...spread(row, range), manual: !same };
}

/** Rows still waiting on a decision — the tab badge, and the publish blocker. */
export function unresolvedRows(
  rows: MappingRow[],
  choices: MappingChoices,
  bands: Band[]
): MappingRow[] {
  return rows.filter((row) => resolveTarget(row, choices, bands) === null);
}

const round6 = (value: number) => Math.round(value * 1e6) / 1e6;

/**
 * The rows as mapping rules, in the shape the backend validates: per source
 * tier one rule per division of the range, weights summing to 1, exactly one
 * primary. `weight` records how the old division's players spread; `is_primary`
 * is where each of them lands. A row without a target — or with a target that
 * has no tier id yet — is left out, which keeps the mapping incomplete.
 */
export function mappingRules(
  rows: MappingRow[],
  choices: MappingChoices,
  bands: Band[]
): DivisionGridMappingRule[] {
  const rules: DivisionGridMappingRule[] = [];
  for (const row of rows) {
    const sourceTierId = row.source.id;
    const target = resolveTarget(row, choices, bands);
    if (sourceTierId === undefined || !target || target.range.some((band) => band.id === undefined)) {
      continue;
    }

    const secondary = target.range
      .map((band, index) => ({
        source_tier_id: sourceTierId,
        target_tier_id: band.id!,
        weight: round6(target.weights[index]),
        is_primary: false
      }))
      .filter((rule) => rule.target_tier_id !== target.primary.id && rule.weight > 0);
    rules.push({
      source_tier_id: sourceTierId,
      target_tier_id: target.primary.id!,
      weight: round6(1 - secondary.reduce((sum, rule) => sum + rule.weight, 0)),
      is_primary: true
    });
    rules.push(...secondary);
  }
  return rules;
}
