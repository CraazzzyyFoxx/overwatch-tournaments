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
import type {
  EncounterGame,
  PickBanEligible,
  PickBanEntry,
  PickBanEntryStatus,
  PickBanGame,
  PickBanKind,
  PickBanMember,
  PickBanResolvedStep,
  PickBanSession,
  PickBanState,
  PickBanStepAction,
  PickBanSubmission,
  PickBanSubmissionItem,
  VetoUnavailableReason
} from "@/types/tournament.types";

import { duelSeats, type Duel } from "@/lib/encounter/seats";
import type { EncounterTeam } from "@/types/encounter.types";

/** How long a draft edit waits before it is saved, so five quick clicks are one request. */
export const DRAFT_SAVE_DELAY_MS = 300;

/** The character catalog's pick-ban kind. Its wire value (DB enum, realtime domain `pick-ban:hero`) is still `hero`. */
export const CHARACTER_PICK_BAN_KIND: PickBanKind = "hero";

/**
 * One participation of the room as its components name it: `id` is the
 * `EncounterTeam.id` every pick-ban write and read addresses, `slot` fixes the
 * order (and the accent: slot 1 teal, slot 2 rose).
 */
export interface PickBanSeat {
  id: number;
  slot: number;
  name: string;
}

/** The room's participations from the encounter's live seats, in slot order. */
export function pickBanSeats(teams: readonly PickBanSeat[]): PickBanSeat[] {
  return [...teams]
    .sort((a, b) => a.slot - b.slot)
    .map(({ id, slot, name }) => ({ id, slot, name }));
}

/** A participation's display name; empty string for one the room does not know. */
export function seatName(seats: readonly PickBanSeat[], teamId: number | null | undefined): string {
  return seats.find((seat) => seat.id === teamId)?.name ?? "";
}

/** A mix player's name (`state.members`); empty string for one the room does not know. */
export function memberName(members: readonly PickBanMember[], memberId: number): string {
  return members.find((member) => member.id === memberId)?.name ?? "";
}

/**
 * A member step's player choice (spec §11.6 R4-3, R4-9): whom the viewer may pick for -- themselves, as captain their
 * teammates still owing, as a host anyone still owing -- and whom the pick is for: `chosen` while they still owe, else
 * the first of them. Nothing to choose off a member step.
 */
export function memberChoice(
  state: PickBanState,
  isAdmin: boolean,
  chosen: number | null
): { choosable: number[]; acting: number | null } {
  const choosable =
    state.current_step?.member == null
      ? []
      : isAdmin
        ? [
            ...state.viewer_member_ids,
            ...state.acting_member_ids.filter((id) => !state.viewer_member_ids.includes(id))
          ]
        : state.viewer_can_act
          ? state.viewer_member_ids
          : [];
  return { choosable, acting: chosen != null && choosable.includes(chosen) ? chosen : (choosable[0] ?? null) };
}

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
 * One proven `Match` row per 1-based position. A null map ID means the
 * game's map was not expanded; the row must still name its exact position.
 * Unbound observations remain separate history, even on the same map.
 */
export function seriesMatchesByPosition<T extends SeriesMatchLike>(
  matches: T[],
  mapIds: (number | null)[]
): (T | null)[] {
  return mapIds.map((mapId, index) =>
    matches.find(
      (match) => match.map_index === index + 1 && (mapId == null || match.map_id === mapId)
    ) ?? null
  );
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
  game: EncounterGame | PickBanGame | null,
  seats: readonly Pick<EncounterTeam, "id" | "slot">[] | null | undefined
): Duel<number> | null {
  if (game == null || game.state !== "confirmed") return null;
  const lines = "teams" in game ? game.teams : game.results;
  const [one, two] = duelSeats(seats);
  const scoreOf = (seat: Pick<EncounterTeam, "id"> | null) =>
    lines.find((line) => line.encounter_team_id === seat?.id)?.score ?? null;
  const oneScore = scoreOf(one);
  const twoScore = scoreOf(two);
  if (oneScore == null || twoScore == null) return null;
  return { one: oneScore, two: twoScore };
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
  /** The acting participations (`EncounterTeam.id`), in resolved order; empty for an engine-resolved step. */
  actors: number[];
  /** No captain acts here — the engine rolls it (`actors: [null]`). */
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
  const actors = step.actors.filter((actor): actor is number => actor !== null);
  return {
    action: step.action,
    actors,
    system: actors.length === 0,
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

/**
 * The viewer's own submission on the step in play, or null (no step, spectator, nothing sent). On a member step it is
 * the answer of `memberId`, the player being picked for: a teammate's lock is not theirs. A team step never reads a
 * member's row.
 */
export function viewerSubmission(state: PickBanState, memberId: number | null = null): PickBanSubmission | null {
  if (state.current_step_index == null) return null;
  const rows = stepSubmissions(state.submissions, state.current_step_index);
  if (memberId != null) return rows.find((row) => row.team_member_id === memberId) ?? null;
  if (state.viewer_team_id == null) return null;
  return (
    rows.find((row) => row.encounter_team_id === state.viewer_team_id && row.team_member_id == null) ?? null
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
  const teamsByItem = new Map<number, Set<number>>();
  for (const submission of submissions) {
    for (const item of submission.items) {
      const teams = teamsByItem.get(item.item_id) ?? new Set<number>();
      teams.add(submission.encounter_team_id);
      teamsByItem.set(item.item_id, teams);
    }
  }
  return new Set(
    [...teamsByItem.entries()].filter(([, teams]) => teams.size > 1).map(([itemId]) => itemId)
  );
}

/** `EncounterTeam.id` -> the items that participation applied. */
export type PickBanItemsByTeam = Record<number, PickBanSubmissionItem[]>;

/**
 * What each participation applied, in step then item order — optionally
 * narrowed to one round and one action.
 *
 * Read from the submissions, never from the board: a blind step where both
 * participations banned the same hero writes ONE banned entry with one
 * `picked_by_team_id`, so the board alone would credit the ban to whichever
 * the projection walked first and leave the other a ban short.
 */
export function appliedItemsByTeam(
  sequence: PickBanResolvedStep[],
  submissions: PickBanSubmission[],
  filter: { round?: number | null; action?: PickBanStepAction } = {}
): PickBanItemsByTeam {
  const items: PickBanItemsByTeam = {};
  for (const step of sequence) {
    if (filter.round !== undefined && step.round !== filter.round) continue;
    if (filter.action !== undefined && step.action !== filter.action) continue;
    for (const submission of stepSubmissions(submissions, step.index)) {
      // Applied = revealed, or any draft of an OPEN step: an open step's
      // choices are public the moment they are made (spec §5).
      if (step.blind && submission.state !== "revealed") continue;
      (items[submission.encounter_team_id] ??= []).push(...submission.items);
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

/**
 * Ids of the bans in `groups` that no longer bind `round`, the round in force.
 *
 * A round's board carries exactly the earlier bans whose `lifetime` still
 * covers it, each naming its origin round, so an earlier ban is active iff
 * `round` holds a ban of the same item from the same origin. The origin
 * matters: a hero can be banned again once an earlier ban on it ran out.
 */
export function expiredBanIds(groups: PickBanRoundGroup[], round: number): Set<number> {
  const origin = (entry: PickBanEntry) => `${entry.carried_from_round ?? entry.round}:${entry.item_id}`;
  const active = new Set(
    groups
      .find((group) => group.round === round)
      ?.entries.filter((entry) => entry.status === "banned")
      .map(origin)
  );
  const expired = new Set<number>();
  for (const group of groups) {
    if (group.round >= round) continue;
    for (const entry of group.entries) {
      if (entry.status === "banned" && !active.has(origin(entry))) expired.add(entry.id);
    }
  }
  return expired;
}

export type PickBanStatusLabelKey = `status.${PickBanEntryStatus | "remaining"}`;

/**
 * Which `status.*` key labels `entry`.
 *
 * `remaining` is the decider-survivor case: reachable only in round mode, when
 * nobody picked the entry and it is simply what the sequence left standing.
 */
export function statusLabelKey(entry: PickBanEntry): PickBanStatusLabelKey {
  if (entry.round != null && entry.status === "picked" && entry.picked_by_kind === "decider") {
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

/**
 * A character's class, lowercased: the group vocabulary `item_group` conditions name and the grid filters by.
 * It is catalog data of the item (`attrs.class`) -- never a player's assigned role -- and `null` when the catalog
 * has not loaded or the row declares none.
 */
export function characterClassOf(item: { attrs?: Record<string, unknown> } | null | undefined): string | null {
  const value = item?.attrs?.class;
  return typeof value === "string" && value.trim() !== "" ? value.trim().toLowerCase() : null;
}

/**
 * Rank of a class in the module's declared `character_classes` order: declared first, undeclared classes after,
 * "unknown" last. Declarations are compared case-insensitively, like every item group.
 */
export function classRank(group: string | null, declared: readonly string[]): number {
  if (group == null) return declared.length + 1;
  const index = declared.findIndex((code) => code.trim().toLowerCase() === group);
  return index === -1 ? declared.length : index;
}

/** One item as the lobby list names it: its class decides which line it lands on. */
export interface PickBanClassItem {
  itemId: number;
  name: string;
  /** `characterClassOf` of the catalog row; null is the "class unknown" bucket. */
  group: string | null;
}

export interface PickBanClassGroup<T extends PickBanClassItem = PickBanClassItem> {
  /** Null is the "class unknown" bucket -- rendered last, never dropped. */
  group: string | null;
  items: T[];
}

/**
 * Items grouped by class in the module's declared order, names sorted inside each group. A class the module does
 * not declare sorts after the declared ones by name; the unknown bucket comes last so a catalog that has not
 * loaded yet never hides an item.
 */
export function groupItemsByClass<T extends PickBanClassItem>(
  items: T[],
  declared: readonly string[] = []
): PickBanClassGroup<T>[] {
  const byGroup = new Map<string | null, T[]>();
  for (const item of items) {
    const bucket = byGroup.get(item.group) ?? [];
    bucket.push(item);
    byGroup.set(item.group, bucket);
  }
  return [...byGroup.entries()]
    .sort(
      ([left], [right]) =>
        classRank(left, declared) - classRank(right, declared) || (left ?? "").localeCompare(right ?? "")
    )
    .map(([group, bucket]) => ({
      group,
      items: [...bucket].sort((left, right) => left.name.localeCompare(right.name))
    }));
}

/**
 * The text the "copy for the lobby" button puts on the clipboard: one line per
 * class, so a captain reads it off while ticking characters off in the
 * custom-game list, which is itself grouped by class.
 */
export function lobbyCopyText(
  groups: PickBanClassGroup[],
  groupLabel: (group: string | null) => string
): string {
  return groups
    .map((group) => `${groupLabel(group.group)}: ${group.items.map((item) => item.name).join(", ")}`)
    .join("\n");
}
