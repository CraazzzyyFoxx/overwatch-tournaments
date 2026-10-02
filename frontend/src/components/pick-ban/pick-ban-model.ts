/**
 * Pure helpers for the generic pick-ban room (map + hero kinds), ruleset v2.
 *
 * The session no longer carries a flat token sequence: it carries RESOLVED
 * STEPS (`PickBanResolvedStep`), each naming its acting sides, how many items
 * they choose, whether the choice is blind, whether every item names an
 * opponent player, and how long a ban lives. What a side actually chose lives
 * in `PickBanSubmission`s — the board (`PickBanEntry`) is a projection of them,
 * and a blind step's submissions merge duplicates into ONE banned entry, so
 * per-side lists have to be read off the submissions rather than the board
 * (design: docs/plans/2026-09-28-pick-ban-constructor.md).
 */
import type { AqtRoleKey } from "@/lib/roster/player-role";
import type {
  EncounterGame,
  PickBanEligible,
  PickBanEntry,
  PickBanEntryStatus,
  PickBanGame,
  PickBanResolvedStep,
  PickBanSession,
  PickBanState,
  PickBanStepAction,
  PickBanSubmission,
  PickBanSubmissionItem,
  VetoUnavailableReason
} from "@/types/tournament.types";

export type PickBanSide = "home" | "away";

/**
 * Picked items in their final play order (action_index, legacy `order`
 * fallback).
 *
 * For a map pool this IS the series' map order, and index + 1 is the round:
 * rounds resolve in order, in slot mode (one pick per round) and in the legacy
 * flat one (the whole order picked up front) alike.
 */
export function pickedItemsInOrder(pool: PickBanEntry[]): PickBanEntry[] {
  return pool
    .filter((entry) => entry.status === "picked")
    .sort((left, right) => (left.action_index ?? left.order) - (right.action_index ?? right.order));
}

/** The fields of a `Match` row the series strip reads. */
export interface SeriesMatchLike {
  map_id: number;
  map_index: number | null;
}

/**
 * One `Match` row per position of the series, 1-based, aligned with `mapIds`
 * (the settled maps in play order — `pickedItemsInOrder`). `null` where nothing
 * has been written for that position yet.
 *
 * The POSITION identifies the row, not the map: a series can play the same map
 * twice, and matching on `map_id` alone printed one play's score on both. A row
 * with no position (every parsed log, and every row written before
 * `Match.map_index` existed) is adopted by the earliest position holding its map
 * that has no exact row — resolved in a second pass, so an exact row is never
 * stolen by an earlier position, and never by two positions at once.
 */
export function seriesMatchesByPosition<T extends SeriesMatchLike>(
  matches: T[],
  mapIds: number[]
): (T | null)[] {
  const claimed = new Set<T>();
  const byPosition = mapIds.map((mapId, index) => {
    const exact = matches.find(
      (match) => !claimed.has(match) && match.map_id === mapId && match.map_index === index + 1
    );
    if (exact != null) claimed.add(exact);
    return exact ?? null;
  });
  return byPosition.map((match, index) => {
    if (match != null) return match;
    const adopted = matches.find(
      (candidate) =>
        !claimed.has(candidate) && candidate.map_id === mapIds[index] && candidate.map_index == null
    );
    if (adopted != null) claimed.add(adopted);
    return adopted ?? null;
  });
}

/**
 * The game at one 1-based position of the series, or null when the payload
 * carries none (a hero-only room, or a position the server has not opened
 * yet).
 *
 * Position, never `map_id`, is what identifies a game: a series may play one
 * map twice, and keying on the map alone showed the earlier play's result on
 * the later one.
 */
export function gameAtPosition(games: PickBanGame[], position: number): PickBanGame | null {
  return games.find((game) => game.position === position) ?? null;
}

/**
 * The accepted score of `game`, or null while it has none.
 *
 * Only a `confirmed` game has one: a dispute, or a single filed claim, is not
 * yet a result, and printing either would tell the captains the position was
 * settled. The server holds the same line before it advances the series.
 */
export function acceptedScore(
  game: EncounterGame | null
): { home: number; away: number } | null {
  if (game == null || game.state !== "confirmed") return null;
  if (game.accepted_home_score == null || game.accepted_away_score == null) return null;
  return { home: game.accepted_home_score, away: game.accepted_away_score };
}

/**
 * The highest round `pool` holds entries for, or null for a flat pool.
 *
 * Read instead of `PickBanState.current_round` when the question is "which
 * round is this session ON", including once that round's steps are all taken:
 * `current_round` is the lowest round with something still available, so a
 * round whose pool is fully consumed (a slot-mode map round always is) reports
 * null the moment it finishes.
 */
export function highestPoolRound(pool: PickBanEntry[]): number | null {
  let highest: number | null = null;
  for (const entry of pool) {
    if (entry.round == null) continue;
    if (highest == null || entry.round > highest) highest = entry.round;
  }
  return highest;
}

/** Session presence gate shared by every action affordance in the room. */
export function isSessionActive(session: PickBanSession | null): boolean {
  return session != null && session.status === "active";
}

/**
 * Epoch-ms deadline of the step on the clock, or null when no countdown should
 * be shown (no timer on the step, session inactive, sequence complete, or an
 * organizer paused the session).
 *
 * The server computes it — `step_deadline` already accounts for the step's own
 * `timer_seconds` and for every reopen that reset the clock, so the room never
 * adds a start time to a duration itself. A paused session has no deadline at
 * all server-side; the guard here keeps a cached state from ticking down to a
 * timeout that cannot happen.
 */
export function stepDeadlineMs(state: PickBanState): number | null {
  if (!isSessionActive(state.session) || state.is_complete) return null;
  if (state.session?.paused_at != null) return null;
  if (!state.step_deadline) return null;
  const deadline = Date.parse(state.step_deadline);
  return Number.isNaN(deadline) ? null : deadline;
}

/** Which empty-room icon a cause warrants; the room resolves it to a component. */
export type PickBanUnavailableIcon = "teams" | "unconfigured" | "misconfigured" | "preview";

export interface PickBanUnavailableCopy {
  /** Keys relative to the `pickBan.room` namespace. */
  titleKey: string;
  hintKey: string;
  icon: PickBanUnavailableIcon;
}

/**
 * Title, hint and icon for every reason the room can be closed — one entry per
 * `VetoUnavailableReason`. The pick-ban engine's config cascade resolves
 * identically for kind=map and kind=hero (same shape, different catalog), so
 * it reuses the SAME reason set the map-veto room already has copy for
 * (backend: `pick_ban_action.get_pick_ban_state` docstring).
 */
export const PICK_BAN_UNAVAILABLE_COPY = {
  not_configured: {
    titleKey: "notConfiguredTitle",
    hintKey: "notConfiguredHint",
    icon: "unconfigured"
  },
  teams_unknown: {
    titleKey: "teamsUnknownTitle",
    hintKey: "teamsUnknownHint",
    icon: "teams"
  },
  slot_count_mismatch: {
    titleKey: "slotCountMismatchTitle",
    hintKey: "slotCountMismatchHint",
    icon: "misconfigured"
  },
  slot_underfilled: {
    titleKey: "slotUnderfilledTitle",
    hintKey: "slotUnderfilledHint",
    icon: "misconfigured"
  },
  not_ready: {
    titleKey: "notReadyTitle",
    hintKey: "notReadyHint",
    icon: "teams"
  },
  waiting_map: {
    titleKey: "waitingMapTitle",
    hintKey: "waitingMapHint",
    icon: "teams"
  },
  bracket_preview: {
    titleKey: "bracketPreviewTitle",
    hintKey: "bracketPreviewHint",
    icon: "preview"
  }
} as const satisfies Record<VetoUnavailableReason, PickBanUnavailableCopy>;

/**
 * A session's reserve snapshot as a lookup by slot position. The column is
 * JSON, so the wire's keys arrive stringified while every slot number in the
 * room is a number — this is where that boundary is crossed.
 * `PickBanSession.slot_reserves` is null for `kind: "hero"`, so this is always
 * empty there.
 */
export function pickBanReserveMap(session: PickBanSession | null): Map<number, number> {
  return new Map(
    Object.entries(session?.slot_reserves ?? {}).map(([position, itemId]) => [
      Number(position),
      itemId
    ])
  );
}

// ─── Resolved steps ─────────────────────────────────────────────────────────

/**
 * Everything a step's headline says, reduced to the pieces a label is built
 * from: "Both teams ban · 5 · blind · one per opponent player · holds for 2
 * maps". Each piece is null/false when it adds nothing, so the caller never
 * renders "×1" or a lifetime on a step that has no ban to outlive the map.
 */
export interface PickBanStepSummary {
  action: PickBanStepAction;
  /** The acting sides, in resolved order; empty for an engine-resolved step. */
  sides: PickBanSide[];
  /** No captain acts here — the engine rolls it (`sides: ["system"]`). */
  system: boolean;
  /** Items per acting side; null when a step takes exactly one. */
  count: number | null;
  blind: boolean;
  /** Every item names an opponent roster player. */
  targeted: boolean;
  /**
   * How long the ban outlives this map: a number of maps, `"series"` for the
   * rest of it, null when there is nothing to say (a one-map ban, or a step
   * that is not a ban at all).
   */
  lifetime: number | "series" | null;
}

export function stepSummary(step: PickBanResolvedStep): PickBanStepSummary {
  const sides = step.sides.filter((side): side is PickBanSide => side !== "system");
  return {
    action: step.action,
    sides,
    system: sides.length === 0,
    count: step.count > 1 ? step.count : null,
    blind: step.blind,
    targeted: step.target != null,
    lifetime:
      step.action !== "ban" || step.lifetime === 1 ? null : (step.lifetime ?? "series")
  };
}

export interface PickBanStepRoundGroup {
  /** The round (map-of-the-series) these steps resolve; 1-based. */
  round: number;
  steps: PickBanResolvedStep[];
}

/**
 * The resolved sequence split across the rounds it resolves, or null for a
 * flat (non-progressive) session.
 *
 * Each step carries its own `round` now, so the grouping is read straight off
 * the sequence instead of being inferred from how many pool entries a round
 * has — a blind step takes five items from each side in ONE step, and the old
 * entry-counting split would have torn that round apart.
 */
export function stepRoundGroups(
  sequence: PickBanResolvedStep[]
): PickBanStepRoundGroup[] | null {
  const byRound = new Map<number, PickBanResolvedStep[]>();
  for (const step of sequence) {
    if (step.round == null) continue;
    const bucket = byRound.get(step.round);
    if (bucket) bucket.push(step);
    else byRound.set(step.round, [step]);
  }
  if (byRound.size === 0) return null;
  return [...byRound.entries()]
    .sort(([left], [right]) => left - right)
    .map(([round, steps]) => ({ round, steps }));
}

export interface PickBanRoundGroup {
  /** The round (map-of-the-series) this group resolves; 1-based. */
  round: number;
  entries: PickBanEntry[];
}

/**
 * `pool` grouped by round in ascending play order, or null for a flat
 * (non-progressive) pool.
 *
 * Mode is read off the entries' `round`, never off `PickBanState.current_round`
 * — which goes null again the instant the sequence completes, so inferring
 * mode from it would render a finished progressive session as a flat one.
 */
export function poolRoundGroups(pool: PickBanEntry[]): PickBanRoundGroup[] | null {
  const byRound = new Map<number, PickBanEntry[]>();
  for (const entry of pool) {
    if (entry.round == null) continue;
    const bucket = byRound.get(entry.round);
    if (bucket) bucket.push(entry);
    else byRound.set(entry.round, [entry]);
  }
  if (byRound.size === 0) return null;
  return [...byRound.entries()]
    .sort(([left], [right]) => left - right)
    .map(([round, entries]) => ({ round, entries }));
}

export type PickBanRoundState = "current" | "resolved" | "upcoming";

/**
 * Where `group` stands, given the server's `current_round`.
 *
 * `current_round` is null for a completed sequence as well as a flat one, so
 * "resolved" is decided by the group having nothing left to act on rather
 * than by comparing against it.
 */
export function roundState(
  group: PickBanRoundGroup,
  currentRound: number | null
): PickBanRoundState {
  if (group.round === currentRound) return "current";
  return group.entries.some((entry) => entry.status === "available") ? "upcoming" : "resolved";
}

// ─── Submissions ────────────────────────────────────────────────────────────

/**
 * The visible submissions of one step, at its CURRENT attempt only.
 *
 * A disputed step keeps its earlier attempts on the wire so the room can tell
 * how many reopens are left; only the newest one is the board.
 */
export function stepSubmissions(
  submissions: PickBanSubmission[],
  stepIndex: number
): PickBanSubmission[] {
  const rows = submissions.filter((submission) => submission.step_index === stepIndex);
  if (rows.length === 0) return [];
  const attempt = rows.reduce((max, row) => Math.max(max, row.attempt), 1);
  return rows.filter((row) => row.attempt === attempt);
}

/** The viewer's own submission on the step in play, or null (no step, spectator, nothing sent). */
export function viewerSubmission(state: PickBanState): PickBanSubmission | null {
  if (state.current_step_index == null || state.viewer_side == null) return null;
  return (
    stepSubmissions(state.submissions, state.current_step_index).find(
      (submission) => submission.side === state.viewer_side
    ) ?? null
  );
}

/**
 * The newest blind step whose drafts are all out in the open — the one the
 * reveal panel prints and the one a dispute reopens.
 *
 * Walked from the end rather than read off `dispute.step_index`: the panel is
 * shown to everyone (a spectator, the side that cannot dispute any more), and
 * `dispute.available` is the VIEWER's own permission, not a statement about
 * which step just resolved.
 */
export function lastRevealedBlindStep(
  sequence: PickBanResolvedStep[],
  submissions: PickBanSubmission[]
): PickBanResolvedStep | null {
  for (let index = sequence.length - 1; index >= 0; index -= 1) {
    const step = sequence[index];
    if (!step.blind) continue;
    const rows = stepSubmissions(submissions, step.index);
    if (rows.length > 0 && rows.every((row) => row.state === "revealed")) return step;
  }
  return null;
}

/**
 * The viewer's own draft for the step in play — what the tray shows and what
 * `submitDraft` replaces. Empty once they locked nothing, and also the seed a
 * dispute prefills.
 */
export function viewerDraftItems(state: PickBanState): PickBanSubmissionItem[] {
  return viewerSubmission(state)?.items ?? [];
}

/**
 * Items both sides named in the same (blind) step. Each side banned it
 * independently and the board merges them into one entry, so the reveal marks
 * them rather than silently showing one side a ban it did not spend.
 */
export function duplicateItemIds(submissions: PickBanSubmission[]): Set<number> {
  const sidesByItem = new Map<number, Set<string>>();
  for (const submission of submissions) {
    for (const item of submission.items) {
      const sides = sidesByItem.get(item.item_id) ?? new Set<string>();
      sides.add(submission.side);
      sidesByItem.set(item.item_id, sides);
    }
  }
  return new Set(
    [...sidesByItem.entries()].filter(([, sides]) => sides.size > 1).map(([itemId]) => itemId)
  );
}

export interface PickBanSideItems {
  home: PickBanSubmissionItem[];
  away: PickBanSubmissionItem[];
}

/**
 * What each side applied, in step then item order — optionally narrowed to one
 * round and one action.
 *
 * Read from the submissions, never from the board: a blind step where both
 * sides banned the same hero writes ONE banned entry with one `picked_by`, so
 * the board alone would credit the ban to whichever side the projection walked
 * first and leave the other side a ban short.
 */
export function appliedItemsBySide(
  sequence: PickBanResolvedStep[],
  submissions: PickBanSubmission[],
  filter: { round?: number | null; action?: PickBanStepAction } = {}
): PickBanSideItems {
  const items: PickBanSideItems = { home: [], away: [] };
  for (const step of sequence) {
    if (filter.round !== undefined && step.round !== filter.round) continue;
    if (filter.action !== undefined && step.action !== filter.action) continue;
    for (const submission of stepSubmissions(submissions, step.index)) {
      // Applied = revealed, or any draft of an OPEN step: an open step's
      // choices are public the moment they are made (spec §5).
      if (submission.side === "system") continue;
      if (step.blind && submission.state !== "revealed") continue;
      items[submission.side].push(...submission.items);
    }
  }
  return items;
}

// ─── The board ──────────────────────────────────────────────────────────────

/**
 * Whether `entry` belongs to `round`. Non-obvious on its own: a FLAT pool's
 * entries carry no round and belong to every one of them, so this is not a
 * plain equality and both readers below depend on that.
 */
function inRound(entry: PickBanEntry, round: number | null): boolean {
  return round == null ? entry.round == null : entry.round == null || entry.round === round;
}

/**
 * Bans of `round` that were spent on an EARLIER map and are still in force
 * (their `lifetime` covers this one). They are fixed: no undo, no dispute and
 * no projection ever touches them, and the room badges them with the map they
 * came from so a captain does not go looking for who banned them here.
 */
export function carriedBanEntries(pool: PickBanEntry[], round: number | null): PickBanEntry[] {
  return pool.filter((entry) => entry.carried_from_round != null && inRound(entry, round));
}

/** Everything banned for `round`, carried bans included — what the lobby has to disable. */
export function bannedEntries(pool: PickBanEntry[], round: number | null): PickBanEntry[] {
  return pool.filter((entry) => entry.status === "banned" && inRound(entry, round));
}

export type PickBanStatusLabelKey = `status.${PickBanEntryStatus | "remaining"}`;

/**
 * Which `status.*` key labels `entry`.
 *
 * `remaining` is the decider-survivor case: reachable only in round mode, when
 * nobody picked the entry and it is simply what the sequence left standing.
 */
export function statusLabelKey(entry: PickBanEntry): PickBanStatusLabelKey {
  if (entry.round != null && entry.status === "picked" && entry.picked_by === "decider") {
    return "status.remaining";
  }
  return `status.${entry.status}`;
}

/**
 * The item ids the viewer may choose right now, or null when the server said
 * nothing (they cannot act, so nothing is greyed as "illegal for you").
 *
 * On a target step the legal set differs per opponent player — a hero whose
 * class matches one player is not a legal ban for another — so naming the
 * selected target narrows it to that player's own set.
 */
export function eligibleItemIds(
  eligible: PickBanEligible | null,
  targetPlayerId: number | null
): Set<number> | null {
  if (eligible == null) return null;
  if (targetPlayerId != null && eligible.by_target != null) {
    return new Set(eligible.by_target[String(targetPlayerId)] ?? []);
  }
  return new Set(eligible.item_ids);
}

export interface PickBanTileStatus {
  /** A click fires: it acts, or adds/removes the item from a blind draft. */
  selectable: boolean;
  /** The viewer may act, but this item is not a legal choice — greyed, inert. */
  ineligible: boolean;
  /** Already in the viewer's own draft for this blind step. */
  drafted: boolean;
  /** Belongs to a round that has not opened yet. */
  locked: boolean;
}

/**
 * How one tile stands for the viewer, given what the server says they may
 * choose (`eligible`) and what they have drafted so far.
 *
 * Legality is the SERVER's answer, never re-derived here: v2 rules are
 * arbitrary condition trees (class must match the target player's role, not
 * banned by this side earlier in the series, at most one per role), and the
 * room's job is to grey what `eligible` omits rather than to reimplement the
 * engine. A drafted item stays clickable — that click takes it back out.
 */
export function tileStatus(
  entry: PickBanEntry,
  {
    canSelect,
    currentRound,
    eligibleIds,
    draftItemIds
  }: {
    canSelect: boolean;
    currentRound: number | null;
    eligibleIds: Set<number> | null;
    draftItemIds: ReadonlySet<number>;
  }
): PickBanTileStatus {
  const locked = entry.round != null && entry.round !== currentRound;
  const drafted = draftItemIds.has(entry.item_id);
  if (!canSelect || entry.status !== "available" || locked) {
    return { selectable: false, ineligible: false, drafted, locked };
  }
  const allowed = drafted || eligibleIds == null || eligibleIds.has(entry.item_id);
  return { selectable: allowed, ineligible: !allowed, drafted, locked };
}

// ─── Lobby copy ─────────────────────────────────────────────────────────────

/** One item as the lobby list names it: its role decides which line it lands on. */
export interface PickBanRoleItem {
  itemId: number;
  name: string;
  role: AqtRoleKey | null;
}

export interface PickBanRoleGroup<T extends PickBanRoleItem = PickBanRoleItem> {
  /** Null is the "role unknown" bucket — rendered last, never dropped. */
  role: AqtRoleKey | null;
  items: T[];
}

/** Tank-damage-support, the order the game's own hero list uses. */
const ROLE_ORDER: AqtRoleKey[] = ["tank", "damage", "support"];

/**
 * Items grouped by role in the game's own order, names sorted inside each
 * group. Empty roles are dropped; the unknown-role bucket comes last so a
 * catalog that has not loaded yet never hides an item.
 */
export function groupItemsByRole<T extends PickBanRoleItem>(items: T[]): PickBanRoleGroup<T>[] {
  const byRole = new Map<AqtRoleKey | null, T[]>();
  for (const item of items) {
    const bucket = byRole.get(item.role) ?? [];
    bucket.push(item);
    byRole.set(item.role, bucket);
  }
  const order: (AqtRoleKey | null)[] = [...ROLE_ORDER, null];
  return order
    .filter((role) => (byRole.get(role)?.length ?? 0) > 0)
    .map((role) => ({
      role,
      items: [...byRole.get(role)!].sort((left, right) => left.name.localeCompare(right.name))
    }));
}

/**
 * The text the "copy for the lobby" button puts on the clipboard: one line per
 * role, so a captain reads it off while ticking heroes off in the custom-game
 * hero list, which is itself grouped by role.
 */
export function lobbyCopyText(
  groups: PickBanRoleGroup[],
  roleLabel: (role: AqtRoleKey | null) => string
): string {
  return groups
    .map((group) => `${roleLabel(group.role)}: ${group.items.map((item) => item.name).join(", ")}`)
    .join("\n");
}
