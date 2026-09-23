/**
 * Pure helpers for the generic pick-ban room (map + hero kinds).
 *
 * Successor to the retired slot-based map-veto model: this engine is
 * round-based (`PickBanEntry.round`), adds `protect` as a third action, and
 * drops the `map_id`/`slot` naming for the pool-agnostic `item_id`/`round`
 * (design: docs/plans/2026-08-09-generic-pickban-engine.md).
 */
import type {
  EncounterGame,
  PickBanAction,
  PickBanEntry,
  PickBanEntryStatus,
  PickBanGame,
  PickBanSession,
  PickBanState,
  VetoUnavailableReason
} from "@/types/tournament.types";

export type PickBanSide = "home" | "away";
type PickBanStepAction = PickBanAction | "decider";

export interface ParsedPickBanStep {
  token: string;
  action: PickBanStepAction;
  side: PickBanSide | null;
}

/** Resolved sequence tokens are "ban_home" / "pick_away" / "protect_home" / "decider". */
export function parseStepToken(token: string): ParsedPickBanStep {
  if (token === "decider") {
    return { token, action: "decider", side: null };
  }
  const [action, side] = token.split("_");
  const resolvedAction: PickBanAction =
    action === "pick" ? "pick" : action === "protect" ? "protect" : "ban";
  return {
    token,
    action: resolvedAction,
    side: side === "away" ? "away" : "home"
  };
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

/**
 * Epoch-ms deadline of the current turn, or null when the timer indicator
 * should not be shown (no timer configured, session inactive, sequence
 * complete).
 */
export function turnDeadlineMs(state: PickBanState): number | null {
  const session = state.session;
  if (!session || session.status !== "active" || state.is_complete) return null;
  if (session.turn_timer_seconds == null || !session.current_step_started_at) return null;
  const startedAt = Date.parse(session.current_step_started_at);
  if (Number.isNaN(startedAt)) return null;
  return startedAt + session.turn_timer_seconds * 1000;
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

export interface PickBanStepRoundGroup extends PickBanRoundGroup {
  /** Positions in the session `sequence` that resolve this round, ascending. */
  stepIndices: number[];
}

/**
 * The session `sequence` split across the rounds it resolves, or null for a
 * flat pool. Each round claims as many consecutive steps as it has pool
 * entries, riding the entries along so the timeline can ask `roundState`
 * about a group directly.
 */
export function stepRoundGroups(
  sequence: string[],
  pool: PickBanEntry[]
): PickBanStepRoundGroup[] | null {
  const groups = poolRoundGroups(pool);
  if (groups === null) return null;
  let cursor = 0;
  return groups.map((group) => {
    const end = Math.min(cursor + group.entries.length, sequence.length);
    const stepIndices: number[] = [];
    for (let index = cursor; index < end; index += 1) stepIndices.push(index);
    cursor = end;
    return { ...group, stepIndices };
  });
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

/**
 * Whether the viewer may select `entry` right now.
 *
 * A protected entry is never selectable by a `ban` (the grid still shows it as
 * `available`-looking to no one, since `protect` is
 * a same-side immunity, not a public "safe" marker other sides can act around
 * differently — the server is the single source of truth for what a click
 * resolves to, this only gates whether the click fires at all).
 */
export function isEntrySelectable(
  entry: PickBanEntry,
  { canSelect, currentRound }: { canSelect: boolean; currentRound: number | null }
): boolean {
  if (!canSelect || entry.status !== "available") return false;
  return entry.round == null || entry.round === currentRound;
}

/**
 * How the configured attribute-uniqueness rule
 * (`PickBanConfig.unique_attribute_per_side_per_round`, exposed as
 * `PickBanState.unique_attribute`) constrains the step in play.
 *
 * Two very different things, deliberately kept apart:
 *
 * - `blocked` — the rule REJECTS it. The side on the clock already took an
 *   action of this kind on that attribute value this round, so the server
 *   answers a 400. The grid disables those tiles rather than letting a captain
 *   discover it by clicking.
 * - `pointless` — perfectly legal, but it buys nothing: on a `protect` step,
 *   an attribute the OPPONENT has already banned this round is one they can no
 *   longer ban again, so protecting it defends against nothing. Greyed as a
 *   hint, never disabled — a captain may still have their own reasons.
 */
export interface PickBanAttributeLocks {
  blocked: Set<string>;
  pointless: Set<string>;
}

const NO_ATTRIBUTE_LOCKS: PickBanAttributeLocks = {
  blocked: new Set(),
  pointless: new Set()
};

/**
 * Resolve the locks for the current step. Empty for every kind/config without
 * the rule, and for a `pick`/`decider` step — neither rulebook restricts those
 * by attribute.
 *
 * Bans and protects never constrain each other (backend:
 * `pick_ban_engine.committed_attributes`), so `blocked` reads only the acting
 * side's OWN actions of the SAME kind.
 */
export function attributeLocks({
  pool,
  uniqueAttribute,
  action,
  side,
  currentRound,
  attributeOf
}: {
  pool: PickBanEntry[];
  uniqueAttribute: string | null | undefined;
  /** The step's expected action — `state.expected_action`. */
  action: PickBanAction | "decider" | null;
  /** The side on the clock — `state.turn_side`, not the viewer's. */
  side: PickBanSide | null;
  currentRound: number | null;
  /** The item's attribute value (hero role today), or null when unknown. */
  attributeOf: (itemId: number) => string | null;
}): PickBanAttributeLocks {
  if (!uniqueAttribute || side == null || (action !== "ban" && action !== "protect")) {
    return NO_ATTRIBUTE_LOCKS;
  }
  const opponent: PickBanSide = side === "home" ? "away" : "home";
  const blocked = new Set<string>();
  const pointless = new Set<string>();

  for (const entry of pool) {
    if (entry.round != null && entry.round !== currentRound) continue;
    const attribute = attributeOf(entry.item_id);
    if (attribute == null) continue;
    if (action === "ban") {
      if (entry.status === "banned" && entry.picked_by === side) blocked.add(attribute);
      continue;
    }
    if (entry.status === "protected" && entry.protected_by === side) blocked.add(attribute);
    // The opponent's ban is what makes a protect moot: they cannot spend a
    // second one on this attribute, so there is nothing left to protect from.
    if (entry.status === "banned" && entry.picked_by === opponent) pointless.add(attribute);
  }
  return { blocked, pointless };
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

/** Session presence gate shared by every action affordance in the room. */
export function isSessionActive(session: PickBanSession | null): boolean {
  return session != null && session.status === "active";
}
