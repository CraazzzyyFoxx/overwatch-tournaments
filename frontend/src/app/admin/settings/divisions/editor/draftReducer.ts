/**
 * The draft division grid: divisions on the workspace's own rank scale, each
 * linked to a run of the Overwatch ladder.
 *
 * Two coordinates, kept apart on purpose. `rankMin` is where a division starts
 * on the scale player ranks are stored on (`rank_min`); its ceiling is the
 * floor above minus one, so native ranges are contiguous by construction. `ow`
 * is the run of ladder ranks an OverFast snapshot resolves into the division
 * (`ow_rank_min` / `ow_rank_max`). On the OW scale the two coincide; on a grid
 * like "New Era x5" — twenty divisions of 100 on 100 … 2099 — they do not, and
 * forcing them together is what re-banded such grids and dropped divisions.
 *
 * `scale` says which coordinate the editor drives:
 *  - `ladder` — rank ranges follow the OW ladder. Divisions are bands that
 *    partition all 45 ranks, cut and joined on the ladder; `rankMin` is derived.
 *  - `custom` — floors are typed. OW runs are linked per division, monotone and
 *    disjoint by construction, and may leave a rank or a division unlinked,
 *    which the publish checks report instead of forbidding mid-edit.
 *
 * Indices, not ranks: a run's `from` / `to` are positions in `LADDER` (0 =
 * Champion 1, 44 = Bronze 5), `from <= to`. The conversion to stored OW values
 * happens once, in `tiersFromBands`, from the ladder artifact.
 *
 * Pure by contract: no React, no services, no clock.
 */

import { OW_REFERENCE_GRID, sortTiersDescending } from "@/lib/divisions/grid";
import type { DivisionTier } from "@/types/workspace.types";

/** The 45 ladder ranks, top first — sorted here because the index arithmetic depends on it. */
export const LADDER: readonly DivisionTier[] = sortTiersDescending(OW_REFERENCE_GRID);

/** Number of OW ladder ranks. */
export const RANK_COUNT = LADDER.length;

const LAST = RANK_COUNT - 1;

/**
 * Bronze 5's floor. A bottom division may start below it: every lower rank
 * resolves into the bottom division anyway, so `0 … 3999` is still a ladder band.
 */
const LADDER_FLOOR = LADDER[LAST].rank_min;

/** Width of one ladder rank on the OW scale. */
const LADDER_STEP = LADDER[0].rank_min - LADDER[1].rank_min;

/** Full name of one ladder rank, e.g. "Grandmaster 4". */
export function rankLabel(index: number): string {
  return LADDER[index]?.name ?? `Rank ${index + 1}`;
}

/** A run of consecutive ladder ranks, as `LADDER` indices. */
export interface OwRun {
  from: number;
  to: number;
}

export interface Band {
  /** Present for a tier that already exists server-side; absent for a new one. */
  id?: number;
  slug: string;
  name: string;
  /** Position from the top, `1`-based. Derived. */
  number: number;
  /** `null` means the band still borrows a ladder crest. */
  icon_url: string | null;
  /** Floor on the grid's own rank scale — the stored `rank_min`. */
  rankMin: number;
  /** The floor above minus one; `null` for the open-ended top division. Derived. */
  rankMax: number | null;
  /** The ladder ranks that land in this division, or `null` when none does. */
  ow: OwRun | null;
}

export type Scale = "ladder" | "custom";

interface HistoryEntry {
  bands: Band[];
  scale: Scale;
  /** The edit that left this state, in a sentence — the log reads it. */
  note: string;
}

export interface DraftState {
  bands: Band[];
  scale: Scale;
  /** One entry per edit, oldest first: the state before it. `undo` pops it. */
  history: HistoryEntry[];
  /** The parent version's bands, for the `vs base` diff. Never mutated. */
  base: Band[];
}

export type Action =
  /** Ladder scale: start a new division at this ladder rank. */
  | { type: "splitAt"; rank: number }
  /** Halve a division — its ladder band, or its native range and OW run. */
  | { type: "split"; bandIndex: number }
  | { type: "merge"; bandIndex: number; into: "up" | "down" }
  /** Move the boundary above ladder rank `rank` by one: `-1` up, `+1` down. */
  | { type: "nudge"; rank: number; delta: -1 | 1 }
  /** Custom scale. */
  | { type: "setFloor"; bandIndex: number; rankMin: number }
  /** Custom scale: link a run, taking its ranks from whichever division held them. */
  | { type: "link"; bandIndex: number; from: number; to: number }
  | { type: "unlink"; bandIndex: number }
  | { type: "setScale"; scale: Scale }
  | { type: "rename"; bandIndex: number; name: string }
  | { type: "setIcon"; bandIndex: number; iconUrl: string }
  | { type: "undo" };

// ---------------------------------------------------------------------------
// Reading a band
// ---------------------------------------------------------------------------

/** Ladder ranks linked to the band; `0` when it has none. */
export function owSize(band: Band): number {
  return band.ow ? band.ow.to - band.ow.from + 1 : 0;
}

/** "Grandmaster 4 – Master 2", one rank's name, or "Not linked". */
export function owRangeLabel(band: Band): string {
  if (!band.ow) return "Not linked";
  return band.ow.from === band.ow.to
    ? rankLabel(band.ow.from)
    : `${rankLabel(band.ow.from)} – ${rankLabel(band.ow.to)}`;
}

/** "GR5–MA2" — the OW run in the width of a table cell; "—" when unlinked. */
export function owShortLabel(band: Band): string {
  if (!band.ow) return "\u2014";
  const short = (index: number) =>
    rankLabel(index).replace(/^(\S{2})\S*\s+(\d+)$/, (_match, stem: string, digit: string) =>
      `${stem.toUpperCase()}${digit}`
    );
  return band.ow.from === band.ow.to
    ? short(band.ow.from)
    : `${short(band.ow.from)}\u2013${short(band.ow.to)}`;
}

/** "1900–1999", or "2000+" for the open-ended top. */
export function rankRangeLabel(band: Pick<Band, "rankMin" | "rankMax">): string {
  return band.rankMax === null ? `${band.rankMin}+` : `${band.rankMin}\u2013${band.rankMax}`;
}

/** The crest a band shows: its own, else the one of its top OW rank, else the ladder rank at its floor. */
export function bandIconUrl(band: Band): string {
  if (band.icon_url) return band.icon_url;
  const index = band.ow?.from ?? LADDER.findIndex((rank) => rank.rank_min <= band.rankMin);
  return LADDER[index === -1 ? LAST : index].icon_url;
}

/** The band index each ladder rank lands in, top first; `null` where no division takes it. */
export function ladderOwners(bands: Band[]): (number | null)[] {
  const owners: (number | null)[] = Array.from({ length: RANK_COUNT }, () => null);
  bands.forEach((band, index) => {
    if (!band.ow) return;
    for (let rank = band.ow.from; rank <= band.ow.to; rank += 1) owners[rank] = index;
  });
  return owners;
}

/** Ladder ranks that land in no division. */
export function unlinkedRanks(bands: Band[]): number[] {
  return ladderOwners(bands).flatMap((owner, rank) => (owner === null ? [rank] : []));
}

/**
 * Every band owns a run and the runs partition the ladder — the `ladder` scale
 * invariant, and the precondition for switching to it.
 */
export function bandsCoverLadder(bands: Band[]): boolean {
  if (bands.length === 0) return false;
  return bands.every((band, index) => {
    if (!band.ow || band.ow.from > band.ow.to) return false;
    const expectedFrom = index === 0 ? 0 : (bands[index - 1].ow?.to ?? -2) + 1;
    return band.ow.from === expectedFrom && (index < bands.length - 1 || band.ow.to === LAST);
  });
}

/** Floors strictly descend, so every native range is non-empty and none overlap. */
export function floorsDescend(bands: Band[]): boolean {
  return bands.every(
    (band, index) =>
      Number.isInteger(band.rankMin) && (index === 0 || band.rankMin < bands[index - 1].rankMin)
  );
}

/** Why `raw` cannot be this band's floor, or `null` when it can. The reducer applies the same rule. */
export function floorError(bands: Band[], bandIndex: number, raw: string): string | null {
  if (!/^-?\d+$/.test(raw.trim())) return "Enter a whole number.";
  const value = Number(raw);
  const above = bands[bandIndex - 1];
  const below = bands[bandIndex + 1];
  if (above && value >= above.rankMin) return `Must be below ${above.name} (${above.rankMin}).`;
  if (below && value <= below.rankMin) return `Must be above ${below.name} (${below.rankMin}).`;
  return null;
}

// ---------------------------------------------------------------------------
// Edits
// ---------------------------------------------------------------------------

/**
 * Derived fields, recomputed after every edit: position, the ceiling from the
 * floor above, and — on the ladder scale — the floor from the band's run.
 */
function finalize(bands: Band[], scale: Scale): Band[] {
  const floors = bands.map((band) => {
    if (scale !== "ladder" || !band.ow) return band.rankMin;
    return band.ow.to === LAST
      ? Math.min(band.rankMin, LADDER_FLOOR)
      : LADDER[band.ow.to].rank_min;
  });
  return bands.map((band, index) => {
    const number = index + 1;
    const rankMin = floors[index];
    const rankMax = index === 0 ? null : floors[index - 1] - 1;
    return band.number === number && band.rankMin === rankMin && band.rankMax === rankMax
      ? band
      : { ...band, number, rankMin, rankMax };
  });
}

/**
 * A slug for a band that has none yet, from a stem that survives renames and
 * boundary moves — the diff and the mapping rules key on the slug. Suffixed
 * only on a collision with a slug inherited from the parent version.
 */
function freshSlug(bands: Band[], stem: string): string {
  if (!bands.some((band) => band.slug === stem)) return stem;
  let suffix = 2;
  while (bands.some((band) => band.slug === `${stem}-${suffix}`)) suffix += 1;
  return `${stem}-${suffix}`;
}

function freshBand(bands: Band[], rankMin: number, ow: OwRun | null): Band {
  const stem = ow ? (LADDER[ow.from]?.slug ?? `rank-${ow.from + 1}`) : `division-${rankMin}`;
  return {
    slug: freshSlug(bands, stem),
    name: "Untitled division",
    number: 0,
    icon_url: null,
    rankMin,
    rankMax: null,
    ow
  };
}

function hull(upper: OwRun | null, lower: OwRun | null): OwRun | null {
  if (!upper) return lower;
  if (!lower) return upper;
  return { from: Math.min(upper.from, lower.from), to: Math.max(upper.to, lower.to) };
}

function clip(run: OwRun, min: number, max: number): OwRun | null {
  const from = Math.max(run.from, min);
  const to = Math.min(run.to, max);
  if (from > to) return null;
  return from === run.from && to === run.to ? run : { from, to };
}

/**
 * Ladder scale: split the band holding `rank` so a new band starts exactly
 * there. The upper half keeps the division's identity; clicking a rank that
 * already starts a band is a no-op — honouring it would mean an empty band.
 */
function splitAt(bands: Band[], rank: number): Band[] | null {
  if (!Number.isInteger(rank) || rank <= 0 || rank > LAST) return null;
  const index = bands.findIndex((band) => band.ow && rank >= band.ow.from && rank <= band.ow.to);
  const band = bands[index];
  if (!band?.ow || rank === band.ow.from) return null;

  const upper: Band = { ...band, ow: { from: band.ow.from, to: rank - 1 } };
  // The new band inherits the floor, which only survives `finalize` at the bottom of the ladder.
  const lower = freshBand(bands, band.rankMin, { from: rank, to: band.ow.to });
  return [...bands.slice(0, index), upper, lower, ...bands.slice(index + 1)];
}

/**
 * Halve a division. On the ladder scale that is a cut through the middle of its
 * band. On a custom scale the native range is halved (the open-ended top gives
 * up one width of the division below it) and the new lower division takes the
 * lower half of the OW run, if the run has two ranks to share.
 */
function split(bands: Band[], bandIndex: number, scale: Scale): Band[] | null {
  const band = bands[bandIndex];
  if (!band) return null;
  if (scale === "ladder") {
    if (!band.ow || owSize(band) < 2) return null;
    return splitAt(bands, band.ow.from + Math.ceil(owSize(band) / 2));
  }

  const below = bands[bandIndex + 1];
  const width =
    band.rankMax === null
      ? Math.max(1, below ? band.rankMin - below.rankMin : LADDER_STEP)
      : band.rankMax - band.rankMin + 1;
  if (band.rankMax !== null && width < 2) return null;
  const upperFloor = band.rankMax === null ? band.rankMin + width : band.rankMin + Math.floor(width / 2);

  let upperRun = band.ow;
  let lowerRun: OwRun | null = null;
  if (band.ow && owSize(band) >= 2) {
    const middle = band.ow.from + Math.ceil(owSize(band) / 2);
    upperRun = { from: band.ow.from, to: middle - 1 };
    lowerRun = { from: middle, to: band.ow.to };
  }

  const upper: Band = { ...band, rankMin: upperFloor, ow: upperRun };
  const lower = freshBand(bands, band.rankMin, lowerRun);
  return [...bands.slice(0, bandIndex), upper, lower, ...bands.slice(bandIndex + 1)];
}

/** Fold a band into a neighbour, which inherits its range and OW ranks and keeps its own identity. */
function merge(bands: Band[], bandIndex: number, into: "up" | "down"): Band[] | null {
  const band = bands[bandIndex];
  if (!band || bands.length < 2) return null;

  if (into === "up") {
    const above = bands[bandIndex - 1];
    if (!above) return null;
    const survivor: Band = { ...above, rankMin: band.rankMin, ow: hull(above.ow, band.ow) };
    return [...bands.slice(0, bandIndex - 1), survivor, ...bands.slice(bandIndex + 1)];
  }

  const below = bands[bandIndex + 1];
  if (!below) return null;
  const survivor: Band = { ...below, ow: hull(band.ow, below.ow) };
  return [...bands.slice(0, bandIndex), survivor, ...bands.slice(bandIndex + 2)];
}

/**
 * Move the boundary above ladder rank `rank` by one rank. `-1` hands the rank
 * above the boundary to the side below it, `+1` the other way. On the ladder
 * scale the losing band keeps at least one rank — emptying is `merge`'s job.
 * On a custom scale either side may be "no division", and a band that gives up
 * its last rank simply becomes unlinked.
 */
function nudge(bands: Band[], rank: number, delta: -1 | 1, scale: Scale): Band[] | null {
  if (!Number.isInteger(rank) || rank <= 0 || rank > LAST) return null;
  const owners = ladderOwners(bands);
  const above = owners[rank - 1];
  const below = owners[rank];
  if (above === below) return null;

  const moving = delta === -1 ? rank - 1 : rank;
  const loser = delta === -1 ? above : below;
  const gainer = delta === -1 ? below : above;
  if (scale === "ladder" && (loser === null || gainer === null || owSize(bands[loser]) < 2)) {
    return null;
  }

  return bands.map((band, index) => {
    if (index === loser && band.ow) {
      if (band.ow.from === band.ow.to) return { ...band, ow: null };
      return {
        ...band,
        ow: moving === band.ow.from ? { ...band.ow, from: moving + 1 } : { ...band.ow, to: moving - 1 }
      };
    }
    if (index === gainer) {
      return { ...band, ow: hull(band.ow, { from: moving, to: moving }) };
    }
    return band;
  });
}

/**
 * Link a run to one division. Order is the constraint: a division above may
 * only keep ranks above the run and one below only ranks below it, so taking
 * ranks from a neighbour clips it, and may leave ranks between them unlinked.
 */
function link(bands: Band[], bandIndex: number, from: number, to: number): Band[] | null {
  const band = bands[bandIndex];
  if (!band || !Number.isInteger(from) || !Number.isInteger(to)) return null;
  const low = Math.max(0, Math.min(from, to));
  const high = Math.min(LAST, Math.max(from, to));
  if (low > high || (band.ow?.from === low && band.ow.to === high)) return null;

  return bands.map((entry, index) => {
    if (index === bandIndex) return { ...entry, ow: { from: low, to: high } };
    if (!entry.ow) return entry;
    const run = index < bandIndex ? clip(entry.ow, 0, low - 1) : clip(entry.ow, high + 1, LAST);
    return run === entry.ow ? entry : { ...entry, ow: run };
  });
}

function apply(state: DraftState, action: Exclude<Action, { type: "undo" }>): Band[] | null {
  const { bands, scale } = state;
  const replace = (bandIndex: number, patch: Partial<Band>) =>
    bands.map((band, index) => (index === bandIndex ? { ...band, ...patch } : band));

  switch (action.type) {
    case "splitAt":
      return scale === "ladder" ? splitAt(bands, action.rank) : null;
    case "split":
      return split(bands, action.bandIndex, scale);
    case "merge":
      return merge(bands, action.bandIndex, action.into);
    case "nudge":
      return nudge(bands, action.rank, action.delta, scale);
    case "setFloor": {
      const band = bands[action.bandIndex];
      if (scale !== "custom" || !band || band.rankMin === action.rankMin) return null;
      if (floorError(bands, action.bandIndex, String(action.rankMin)) !== null) return null;
      return replace(action.bandIndex, { rankMin: action.rankMin });
    }
    case "link":
      return scale === "custom" ? link(bands, action.bandIndex, action.from, action.to) : null;
    case "unlink":
      return scale === "custom" && bands[action.bandIndex]?.ow
        ? replace(action.bandIndex, { ow: null })
        : null;
    case "setScale":
      if (action.scale === scale) return null;
      // Following the ladder derives every floor from a run, so every division needs one.
      return action.scale === "custom" || bandsCoverLadder(bands) ? bands : null;
    case "rename": {
      const name = action.name.trim();
      const band = bands[action.bandIndex];
      if (!band || name === "" || name === band.name) return null;
      return replace(action.bandIndex, { name });
    }
    case "setIcon": {
      const band = bands[action.bandIndex];
      if (!band || action.iconUrl === band.icon_url) return null;
      return replace(action.bandIndex, { icon_url: action.iconUrl });
    }
  }
}

/** The edit in a sentence, from the action and the states around it. */
function describe(action: Exclude<Action, { type: "undo" }>, before: Band[], after: Band[]): string {
  switch (action.type) {
    case "splitAt":
    case "split": {
      const known = new Set(before.map((band) => band.slug));
      const added = after.find((band) => !known.has(band.slug));
      const parent = added ? after[after.indexOf(added) - 1] : undefined;
      if (!added || !parent) return "Split a division";
      return action.type === "splitAt"
        ? `Split ${parent.name} at ${rankLabel(added.ow?.from ?? action.rank)}`
        : `Split ${parent.name} — the new division takes ${rankRangeLabel(added)}`;
    }
    case "merge": {
      const gone = before[action.bandIndex];
      const survivor = after[action.into === "up" ? action.bandIndex - 1 : action.bandIndex];
      return `Merged ${gone.name} into ${survivor.name}`;
    }
    case "nudge": {
      const moving = action.delta === -1 ? action.rank - 1 : action.rank;
      const from = ladderOwners(before)[moving];
      const to = ladderOwners(after)[moving];
      const name = (list: Band[], index: number | null) =>
        index === null ? "no division" : list[index].name;
      return `${rankLabel(moving)} moved from ${name(before, from)} to ${name(after, to)}`;
    }
    case "setFloor":
      return `${after[action.bandIndex].name} now starts at ${action.rankMin}`;
    case "link":
      return `Linked ${owRangeLabel(after[action.bandIndex])} to ${after[action.bandIndex].name}`;
    case "unlink":
      return `Unlinked ${before[action.bandIndex].name} from the OW ladder`;
    case "setScale":
      return action.scale === "ladder"
        ? "Rank ranges now follow the OW ladder"
        : "Rank ranges are now a custom scale";
    case "rename":
      return `Renamed ${before[action.bandIndex].name} → ${after[action.bandIndex].name}`;
    case "setIcon":
      return `Set a crest for ${after[action.bandIndex].name}`;
  }
}

export function draftReducer(state: DraftState, action: Action): DraftState {
  if (action.type === "undo") {
    const previous = state.history.at(-1);
    if (!previous) return state;
    return {
      ...state,
      bands: previous.bands,
      scale: previous.scale,
      history: state.history.slice(0, -1)
    };
  }

  const next = apply(state, action);
  // A rejected action returns the same object, so React skips the re-render.
  if (next === null) return state;
  const scale = action.type === "setScale" ? action.scale : state.scale;
  const bands = finalize(next, scale);
  return {
    ...state,
    bands,
    scale,
    history: [
      ...state.history,
      { bands: state.bands, scale: state.scale, note: describe(action, state.bands, bands) }
    ]
  };
}

export function initDraftState(bands: Band[], scale: Scale, base: Band[]): DraftState {
  return { bands: finalize(bands, scale), scale, history: [], base };
}

/** The whole edit log, oldest first. */
export function describeEdits(state: DraftState): string[] {
  return state.history.map((entry) => entry.note);
}

// ---------------------------------------------------------------------------
// Stored tiers <-> bands
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
 * Bands as stored tiers. A ladder rank's `rank_min` IS its OW rank value, so a
 * run is stored as its floor and ceiling ranks' values; an unlinked band stores
 * both as `null`, which the backend reads as "no OW rank lands here".
 */
export function tiersFromBands(bands: Band[]): DraftTierPayload[] {
  return bands.map((band, index) => ({
    ...(band.id === undefined ? {} : { id: band.id }),
    slug: band.slug,
    number: index + 1,
    name: band.name,
    sort_order: index,
    rank_min: band.rankMin,
    rank_max: band.rankMax,
    icon_url: bandIconUrl(band),
    ow_rank_min: band.ow ? LADDER[band.ow.to].rank_min : null,
    ow_rank_max: band.ow ? LADDER[band.ow.from].rank_min : null
  }));
}

function hasOwLink(tier: DivisionTier): boolean {
  return tier.ow_rank_min != null && tier.ow_rank_max != null;
}

/** The backend's order: highest floor first, ties by position. */
function sortedTiers(tiers: DivisionTier[]): DivisionTier[] {
  return [...tiers].sort(
    (left, right) =>
      right.rank_min - left.rank_min ||
      (left.sort_order ?? left.number) - (right.sort_order ?? right.number)
  );
}

/**
 * Stored tiers as bands, resolving the ladder exactly as the backend resolves an
 * OW rank: through the explicit `ow_rank_*` pairs when any tier has one (first
 * match wins), else by rank range with the bottom division as the fallback. A
 * rank that would break the run order — only possible with overlapping stored
 * pairs — is left unlinked rather than guessed.
 */
export function bandsFromTiers(tiers: DivisionTier[]): Band[] {
  if (tiers.length === 0) {
    return finalize(
      [
        {
          slug: "division-1",
          name: "Division 1",
          number: 1,
          icon_url: null,
          rankMin: LADDER_FLOOR,
          rankMax: null,
          ow: { from: 0, to: LAST }
        }
      ],
      "custom"
    );
  }

  const sorted = sortedTiers(tiers);
  const bands: Band[] = [];
  for (const tier of sorted) {
    bands.push({
      ...(tier.id === undefined ? {} : { id: tier.id }),
      slug: tier.slug || freshSlug(bands, `division-${tier.number}`),
      name: tier.name,
      number: bands.length + 1,
      icon_url: tier.icon_url || null,
      rankMin: tier.rank_min,
      rankMax: null,
      ow: null
    });
  }

  const explicit = sorted.some(hasOwLink);
  const ownerOf = (rank: number): number | null => {
    const value = LADDER[rank].rank_min;
    if (explicit) {
      const index = sorted.findIndex(
        (tier) =>
          hasOwLink(tier) &&
          value >= Math.min(tier.ow_rank_min!, tier.ow_rank_max!) &&
          value <= Math.max(tier.ow_rank_min!, tier.ow_rank_max!)
      );
      return index === -1 ? null : index;
    }
    const index = bands.findIndex((band) => band.rankMin <= value);
    return index === -1 ? bands.length - 1 : index;
  };

  let previous: number | null = null;
  let highest = -1;
  for (let rank = 0; rank < RANK_COUNT; rank += 1) {
    const owner = ownerOf(rank);
    if (owner === null || (owner !== previous && owner <= highest)) {
      previous = null;
      continue;
    }
    const band = bands[owner];
    band.ow = band.ow ? { from: band.ow.from, to: rank } : { from: rank, to: rank };
    previous = owner;
    highest = owner;
  }

  return finalize(bands, "custom");
}

/**
 * `ladder` when the stored ranges are exactly bands of the OW ladder and any
 * stored link is the band itself — what "Load standard OW ladder" writes, and
 * the one case where a single edit can drive both coordinates. Anything else
 * opens as `custom`, so the editor never rewrites a scale it did not create.
 */
export function scaleOf(tiers: DivisionTier[]): Scale {
  const bands = bandsFromTiers(tiers);
  if (!bandsCoverLadder(bands)) return "custom";
  const sorted = sortedTiers(tiers);
  const aligned = finalize(bands, "ladder").every(
    (band, index) =>
      band.rankMin === sorted[index].rank_min && band.rankMax === sorted[index].rank_max
  );
  return aligned ? "ladder" : "custom";
}

// ---------------------------------------------------------------------------
// Diff against the parent version
// ---------------------------------------------------------------------------

export type BandVerdict = "new" | "range moved" | "relinked" | "renamed";

function sameRun(left: OwRun | null, right: OwRun | null): boolean {
  return left?.from === right?.from && left?.to === right?.to;
}

function rangeMoved(before: Band, after: Band): boolean {
  return before.rankMin !== after.rankMin || before.rankMax !== after.rankMax;
}

/**
 * How one band differs from the version the draft was created from, or `null`.
 * A moved range outranks a new OW link, which outranks a rename: each changes
 * fewer players' divisions than the one before it.
 */
export function bandVerdict(base: Band[], band: Band): BandVerdict | null {
  const before = base.find((entry) => entry.slug === band.slug);
  if (!before) return "new";
  if (rangeMoved(before, band)) return "range moved";
  if (!sameRun(before.ow, band.ow)) return "relinked";
  if (before.name !== band.name) return "renamed";
  return null;
}

export interface BandDiff {
  added: Band[];
  /** In the parent version, gone from the draft — folded into a neighbour. */
  removed: Band[];
  /** Rank range or OW link changed. */
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
    if (rangeMoved(before, band) || !sameRun(before.ow, band.ow)) {
      diff.moved.push({ before, after: band });
    }
    if (before.name !== band.name) {
      diff.renamed.push({ before, after: band });
    }
  }
  diff.removed = base.filter((band) => !draftSlugs.has(band.slug));
  return diff;
}

/** Bands whose range or link differs from the parent version's — the save-bar's "Z differ". */
export function bandsDifferingFromBase(base: Band[], bands: Band[]): number {
  const diff = diffBands(base, bands);
  return diff.added.length + diff.removed.length + diff.moved.length;
}
