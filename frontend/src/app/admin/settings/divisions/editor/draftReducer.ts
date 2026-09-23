/**
 * The draft division grid as bands of the Overwatch ladder.
 *
 * A division is not a pair of rank numbers the user types — it is a *band* of
 * consecutive ladder ranks. Modelling it that way is what makes the editor's
 * central invariant structural instead of validated: the bands are a partition
 * of `0 … 44`, so a gap or an overlap has no representation to be entered in.
 * Every action below either keeps that partition or is a no-op; nothing here
 * can produce a state a validator would have to reject.
 *
 * Indices, not ranks. `owFrom` / `owTo` are positions in `LADDER` (0 = Champion
 * 1 at the top, 44 = Bronze 5 at the bottom), and `owFrom <= owTo` always. The
 * conversion to the stored `rank_min` / `rank_max` / `ow_rank_min` /
 * `ow_rank_max` quadruple happens once, in `tiersFromBands`, from the ladder
 * artifact — so the front-end ladder and the backend's OW rank mapping cannot
 * drift apart by arithmetic done twice.
 *
 * Pure by contract: no React, no services, no clock. The editor page holds one
 * of these in `useReducer`, and `draftReducer.test.ts` re-asserts the partition
 * after every action.
 */

import { getTierForRank, OW_REFERENCE_GRID, sortTiersDescending } from "@/lib/divisions/grid";
import type { DivisionTier } from "@/types/workspace.types";

/**
 * The 45 ladder ranks, top first.
 *
 * Sorted rather than trusted: `OW_REFERENCE_GRID` is already descending by
 * `rank_min`, but the index arithmetic in this module is only correct for that
 * order, so it is established here instead of assumed.
 */
export const LADDER: readonly DivisionTier[] = sortTiersDescending(OW_REFERENCE_GRID);

/** Number of ladder ranks a draft must cover, end to end. */
export const RANK_COUNT = LADDER.length;

/** Full name of one ladder rank, e.g. "Grandmaster 4". */
export function rankLabel(index: number): string {
  return LADDER[index]?.name ?? `Rank ${index + 1}`;
}

export interface Band {
  /** Present for a tier that already exists server-side; absent for a new one. */
  id?: number;
  slug: string;
  name: string;
  /** Position from the top, `1`-based. Derived — never set by a caller. */
  number: number;
  /** `null` means the band still borrows the crest of its ceiling rank. */
  icon_url: string | null;
  /** Ladder index of the ceiling (highest rank) — the smaller index. */
  owFrom: number;
  /** Ladder index of the floor (lowest rank) — the larger index. */
  owTo: number;
}

export interface DraftState {
  bands: Band[];
  /** One snapshot per edit, oldest first. `undo` pops it; the log reads it. */
  history: Band[][];
  /** The parent version's bands, for the `vs base` diff. Never mutated. */
  base: Band[];
}

export type Action =
  | { type: "splitAt"; rank: number }
  | { type: "moveBoundary"; bandIndex: number; edge: "floor" | "ceiling"; delta: -1 | 1 }
  | { type: "merge"; bandIndex: number; into: "up" | "down" }
  | { type: "rename"; bandIndex: number; name: string }
  | { type: "setIcon"; bandIndex: number; iconUrl: string }
  | { type: "undo" }
  | { type: "splitWidest" };

/** How many ladder ranks the band spans. Never `0` — an empty band is unreachable. */
export function bandSize(band: Band): number {
  return band.owTo - band.owFrom + 1;
}

/** "Grandmaster 4 – Master 2", or a single rank's name for a one-rank band. */
export function bandRangeLabel(band: Band): string {
  return band.owFrom === band.owTo
    ? rankLabel(band.owFrom)
    : `${rankLabel(band.owFrom)} – ${rankLabel(band.owTo)}`;
}

/**
 * "GR5–MA2" — the band in the width of a table cell.
 *
 * Only for the dense places (the Mappings rows, where two grids sit side by
 * side); the divisions table spells the rank names out in full. Two letters of
 * the tier plus its number is unambiguous across the ladder's nine tiers.
 */
export function bandShortLabel(band: Band): string {
  const short = (index: number) =>
    rankLabel(index).replace(/^(\S{2})\S*\s+(\d+)$/, (_match, stem: string, digit: string) =>
      `${stem.toUpperCase()}${digit}`
    );
  return band.owFrom === band.owTo
    ? short(band.owFrom)
    : `${short(band.owFrom)}\u2013${short(band.owTo)}`;
}

/** The crest a band shows: its own, or the one it borrows from its ceiling rank. */
export function bandIconUrl(band: Band): string {
  return band.icon_url ?? LADDER[band.owFrom]?.icon_url ?? "";
}

/**
 * The partition invariant, as a predicate.
 *
 * Exported because the test asserts it after every action rather than trusting
 * each reducer branch to have kept it.
 */
export function bandsCoverLadder(bands: Band[]): boolean {
  if (bands.length === 0) return false;
  if (bands[0].owFrom !== 0) return false;
  if (bands[bands.length - 1].owTo !== RANK_COUNT - 1) return false;
  return bands.every(
    (band, index) =>
      band.owFrom <= band.owTo &&
      (index === 0 || bands[index - 1].owTo + 1 === band.owFrom)
  );
}

function renumber(bands: Band[]): Band[] {
  return bands.map((band, index) => (band.number === index + 1 ? band : { ...band, number: index + 1 }));
}

/**
 * A slug for a band that has none yet.
 *
 * Named after its ceiling rank (`diamond-4`) so it survives later renames and
 * boundary moves — the diff and the mapping rules key on the slug, so a slug
 * derived from the band's position would make every move look like a new
 * division. Suffixed only on the rare collision with a slug inherited from the
 * parent version.
 */
function freshSlug(bands: Band[], owFrom: number): string {
  const stem = LADDER[owFrom]?.slug ?? `band-${owFrom + 1}`;
  if (!bands.some((band) => band.slug === stem)) return stem;
  let suffix = 2;
  while (bands.some((band) => band.slug === `${stem}-${suffix}`)) suffix += 1;
  return `${stem}-${suffix}`;
}

/**
 * Split the band containing `rank` so that a new band starts exactly there.
 *
 * The upper half keeps the original division's identity (id, slug, name,
 * crest); the lower half is the new one, which borrows a crest until it is
 * given its own. Clicking a rank that is already a ceiling is a no-op — the
 * boundary the user asked for is the one already there, and honouring it would
 * mean creating an empty band.
 */
function splitAt(bands: Band[], rank: number): Band[] | null {
  if (!Number.isInteger(rank) || rank <= 0 || rank >= RANK_COUNT) return null;
  const index = bands.findIndex((band) => rank >= band.owFrom && rank <= band.owTo);
  if (index === -1) return null;
  const band = bands[index];
  if (rank === band.owFrom) return null;

  const upper: Band = { ...band, owTo: rank - 1 };
  const lower: Band = {
    slug: freshSlug(bands, rank),
    name: "Untitled division",
    number: band.number + 1,
    icon_url: null,
    owFrom: rank,
    owTo: band.owTo
  };
  return [...bands.slice(0, index), upper, lower, ...bands.slice(index + 1)];
}

/**
 * Move the boundary two neighbours share, by one rank.
 *
 * `delta` is a step along the ladder index: `-1` moves the boundary up (toward
 * Champion), `+1` down (toward Bronze). Whichever band loses the rank keeps at
 * least one, so a band can never be emptied out from the side — emptying is
 * `merge`'s job and has to be asked for explicitly.
 */
function moveBoundary(
  bands: Band[],
  bandIndex: number,
  edge: "floor" | "ceiling",
  delta: -1 | 1
): Band[] | null {
  // Every boundary is one band's ceiling and its neighbour's floor; normalise to
  // "the boundary above `lowerIndex`" so both edges take the same code path.
  const lowerIndex = edge === "ceiling" ? bandIndex : bandIndex + 1;
  const upperIndex = lowerIndex - 1;
  if (upperIndex < 0 || lowerIndex >= bands.length) return null;

  const upper = bands[upperIndex];
  const lower = bands[lowerIndex];
  // delta -1: the boundary rises, the lower band gains the rank the upper loses.
  const shrinking = delta === -1 ? upper : lower;
  if (bandSize(shrinking) < 2) return null;

  const next = [...bands];
  next[upperIndex] = { ...upper, owTo: upper.owTo + delta };
  next[lowerIndex] = { ...lower, owFrom: lower.owFrom + delta };
  return next;
}

/** Fold a band into a neighbour, which inherits its ranks and keeps its own identity. */
function merge(bands: Band[], bandIndex: number, into: "up" | "down"): Band[] | null {
  if (bands.length < 2) return null;
  const band = bands[bandIndex];
  if (!band) return null;

  if (into === "up") {
    const above = bands[bandIndex - 1];
    if (!above) return null;
    const survivor: Band = { ...above, owTo: band.owTo };
    return [...bands.slice(0, bandIndex - 1), survivor, ...bands.slice(bandIndex + 1)];
  }

  const below = bands[bandIndex + 1];
  if (!below) return null;
  const survivor: Band = { ...below, owFrom: band.owFrom };
  return [...bands.slice(0, bandIndex), survivor, ...bands.slice(bandIndex + 2)];
}

/**
 * Split the widest band down the middle — the one-click way out of a draft that
 * needs one more division and no particular boundary.
 */
function splitWidest(bands: Band[]): Band[] | null {
  let widest = -1;
  let widestSize = 1;
  bands.forEach((band, index) => {
    if (bandSize(band) > widestSize) {
      widest = index;
      widestSize = bandSize(band);
    }
  });
  if (widest === -1) return null;
  const band = bands[widest];
  return splitAt(bands, band.owFrom + Math.ceil(bandSize(band) / 2));
}

export function draftReducer(state: DraftState, action: Action): DraftState {
  if (action.type === "undo") {
    const previous = state.history[state.history.length - 1];
    if (!previous) return state;
    return { ...state, bands: previous, history: state.history.slice(0, -1) };
  }

  const next = ((): Band[] | null => {
    switch (action.type) {
      case "splitAt":
        return splitAt(state.bands, action.rank);
      case "splitWidest":
        return splitWidest(state.bands);
      case "moveBoundary":
        return moveBoundary(state.bands, action.bandIndex, action.edge, action.delta);
      case "merge":
        return merge(state.bands, action.bandIndex, action.into);
      case "rename": {
        const name = action.name.trim();
        const band = state.bands[action.bandIndex];
        if (!band || name === "" || name === band.name) return null;
        return state.bands.map((entry, index) =>
          index === action.bandIndex ? { ...entry, name } : entry
        );
      }
      case "setIcon": {
        const band = state.bands[action.bandIndex];
        if (!band || action.iconUrl === band.icon_url) return null;
        return state.bands.map((entry, index) =>
          index === action.bandIndex ? { ...entry, icon_url: action.iconUrl } : entry
        );
      }
    }
  })();

  // A rejected action returns the same object, so React skips the re-render.
  if (next === null) return state;
  return { ...state, bands: renumber(next), history: [...state.history, state.bands] };
}

export function initDraftState(bands: Band[], base: Band[]): DraftState {
  return { bands: renumber(bands), history: [], base };
}

// ---------------------------------------------------------------------------
// Stored tiers <-> ladder bands
// ---------------------------------------------------------------------------

/** The tier payload `updateDivisionGridVersion` / `createDivisionGridVersion` take. */
export interface DraftTierPayload {
  id?: number;
  slug: string;
  number: number;
  name: string;
  sort_order: number;
  rank_min: number;
  rank_max: number | null;
  icon_url: string;
  ow_rank_min: number | null;
  ow_rank_max: number | null;
}

/**
 * Bands as stored tiers.
 *
 * Both rank pairs come from the same ladder rows, which is what keeps the two
 * coordinate systems in agreement: `rank_min` / `rank_max` are the band's SR
 * span (the ceiling tier's `rank_max` is `null` only for the open-ended top of
 * the ladder), and `ow_rank_min` / `ow_rank_max` are the OW `rank_value`s of
 * its floor and ceiling ranks — each ladder row's `rank_min` IS its OW rank
 * value. Both OW endpoints are always filled: the backend's
 * `resolve_division_from_ow_rank` skips any tier with a `null` endpoint, so a
 * half-filled pair would quietly make a division unreachable by OW rank.
 */
export function tiersFromBands(bands: Band[]): DraftTierPayload[] {
  return bands.map((band, index) => {
    const ceiling = LADDER[band.owFrom];
    const floor = LADDER[band.owTo];
    return {
      ...(band.id === undefined ? {} : { id: band.id }),
      slug: band.slug,
      number: index + 1,
      name: band.name,
      sort_order: index,
      rank_min: floor.rank_min,
      rank_max: ceiling.rank_max,
      icon_url: bandIconUrl(band),
      ow_rank_min: floor.rank_min,
      ow_rank_max: ceiling.rank_min
    };
  });
}

/**
 * Stored tiers as bands.
 *
 * Read by walking the ladder rather than the tier list: each ladder rank is
 * resolved through the version exactly as a player's rank would be, and runs of
 * consecutive ranks landing in the same tier become one band. That way a stored
 * version whose ranges do not sit on ladder boundaries still yields a legal
 * partition — the alternative is an editor that opens in a state its own
 * invariant forbids. A tier that owns no ladder rank at all has nothing to
 * edit and does not survive the trip.
 */
export function bandsFromTiers(tiers: DivisionTier[]): Band[] {
  if (tiers.length === 0) {
    return [
      { slug: "division-1", name: "Division 1", number: 1, icon_url: null, owFrom: 0, owTo: RANK_COUNT - 1 }
    ];
  }

  const grid = { tiers };
  const bands: Band[] = [];
  let currentTier: DivisionTier | null = null;

  for (let index = 0; index < RANK_COUNT; index += 1) {
    const tier = getTierForRank(grid, LADDER[index].rank_min);
    const last = bands[bands.length - 1];
    if (last && tier === currentTier) {
      last.owTo = index;
      continue;
    }
    currentTier = tier;
    bands.push({
      ...(tier?.id === undefined ? {} : { id: tier.id }),
      slug: tier?.slug || freshSlug(bands, index),
      name: tier?.name ?? `Division ${bands.length + 1}`,
      number: bands.length + 1,
      icon_url: tier?.icon_url ?? null,
      owFrom: index,
      owTo: index
    });
  }

  return renumber(bands);
}

// ---------------------------------------------------------------------------
// Diff against the parent version
// ---------------------------------------------------------------------------

export type BandVerdict = "new" | "band moved" | "renamed";

/**
 * How one band differs from the version the draft was created from, or `null`
 * when it does not. Structural change outranks a rename: a moved boundary
 * changes which players land in the division, a new name does not.
 */
export function bandVerdict(base: Band[], band: Band): BandVerdict | null {
  const before = base.find((entry) => entry.slug === band.slug);
  if (!before) return "new";
  if (before.owFrom !== band.owFrom || before.owTo !== band.owTo) return "band moved";
  if (before.name !== band.name) return "renamed";
  return null;
}

export interface BandDiff {
  added: Band[];
  /** In the parent version, gone from the draft — folded into a neighbour. */
  removed: Band[];
  moved: { before: Band; after: Band }[];
  renamed: { before: Band; after: Band }[];
}

export function diffBands(base: Band[], bands: Band[]): BandDiff {
  const bySlug = new Map(base.map((band) => [band.slug, band]));
  const draftSlugs = new Set(bands.map((band) => band.slug));

  const diff: BandDiff = { added: [], removed: [], moved: [], renamed: [] };
  for (const band of bands) {
    const before = bySlug.get(band.slug);
    if (!before) {
      diff.added.push(band);
      continue;
    }
    if (before.owFrom !== band.owFrom || before.owTo !== band.owTo) {
      diff.moved.push({ before, after: band });
    }
    if (before.name !== band.name) {
      diff.renamed.push({ before, after: band });
    }
  }
  diff.removed = base.filter((band) => !draftSlugs.has(band.slug));
  return diff;
}

/** Bands whose ladder span differs from the parent version's — the save-bar's "Z bands differ". */
export function bandsDifferingFromBase(base: Band[], bands: Band[]): number {
  const diff = diffBands(base, bands);
  return diff.added.length + diff.removed.length + diff.moved.length;
}

// ---------------------------------------------------------------------------
// The edit log
// ---------------------------------------------------------------------------

/**
 * One edit, in a sentence, read out of the two snapshots around it.
 *
 * `DraftState` keeps snapshots rather than an action log because that is what
 * `undo` needs; the log is derived from the same data instead of being a second
 * source of truth that could disagree with it.
 */
export function describeAction(before: Band[], after: Band[]): string {
  if (after.length > before.length) {
    const beforeSlugs = new Set(before.map((band) => band.slug));
    const added = after.find((band) => !beforeSlugs.has(band.slug));
    const parent = added ? after[after.indexOf(added) - 1] : undefined;
    if (added) {
      return parent
        ? `Split ${parent.name} at ${rankLabel(added.owFrom)}`
        : `New division at ${rankLabel(added.owFrom)}`;
    }
  }

  if (after.length < before.length) {
    const afterSlugs = new Set(after.map((band) => band.slug));
    const gone = before.find((band) => !afterSlugs.has(band.slug));
    if (gone) {
      const survivor = after.find(
        (band) => band.owFrom === gone.owFrom || band.owTo === gone.owTo
      );
      return survivor ? `Merged ${gone.name} into ${survivor.name}` : `Removed ${gone.name}`;
    }
  }

  const bySlug = new Map(before.map((band) => [band.slug, band]));
  const renamed = after.find((band) => {
    const previous = bySlug.get(band.slug);
    return previous !== undefined && previous.name !== band.name;
  });
  if (renamed) {
    return `Renamed ${bySlug.get(renamed.slug)!.name} → ${renamed.name}`;
  }

  const recrested = after.find((band) => {
    const previous = bySlug.get(band.slug);
    return previous !== undefined && previous.icon_url !== band.icon_url;
  });
  if (recrested) return `Set a crest for ${recrested.name}`;

  const shifted = after.find((band) => {
    const previous = bySlug.get(band.slug);
    return previous !== undefined && previous.owFrom !== band.owFrom;
  });
  if (shifted) {
    const previous = bySlug.get(shifted.slug)!;
    const index = after.indexOf(shifted);
    const neighbour = after[index - 1];
    const verb = shifted.owFrom < previous.owFrom ? "lost" : "gained";
    return neighbour
      ? `${shifted.name} now starts at ${rankLabel(shifted.owFrom)} — ${neighbour.name} ${verb} one rank`
      : `${shifted.name} now starts at ${rankLabel(shifted.owFrom)}`;
  }

  return "Edited the draft";
}

/** The whole edit log, oldest first. */
export function describeEdits(state: DraftState): string[] {
  return state.history.map((snapshot, index) =>
    describeAction(snapshot, state.history[index + 1] ?? state.bands)
  );
}
