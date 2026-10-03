import { normalizeRole } from "@/lib/roster/player-role";
import {
  acceptedScore,
  appliedItemsBySide,
  bannedEntries,
  carriedBanEntries,
  gameAtPosition,
  groupItemsByRole,
  highestPoolRound,
  pickedItemsInOrder
} from "@/components/pick-ban/pick-ban-model";
import type { PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import type { Encounter } from "@/types/encounter.types";
import type { PickBanEntry, PickBanGame, PickBanKind, PickBanState } from "@/types/tournament.types";

import type {
  PregameHeroAction,
  PregameHeroBoard,
  PregameHeroRound
} from "./PregameHeroBans";
import type { PregamePhase, PregamePhaseStatus, PregameSeriesMap } from "./PregameHeader";

type ItemLookup = Record<number, PickBanItemLike | undefined>;

export interface PregameLoopState {
  statesByKind: Record<PickBanKind, PickBanState>;
  /** Something WOULD open for this kind once teams/rules/readiness allow it. */
  mapApplies: boolean;
  heroApplies: boolean;
  /** Kinds an organizer cancelled — no phase left, and the room says so. */
  cancelledKinds: PickBanKind[];
  /** Neither kind has a rule set: there is no room to show at all. */
  unconfigured: boolean;
  waitingOnReadiness: boolean;
  /** The maps this series has settled so far, in play order. */
  seriesMaps: PickBanEntry[];
  games: PickBanGame[];
  pendingIndex: number;
  pendingMap: PickBanEntry | null;
  pendingRound: number | null;
  /** The map whose result the report screen collects — `null` outside it. */
  reportRound: number | null;
  phase: PregamePhase;
  phases: PregamePhaseStatus[];
  /** Which map of the series the room is on. */
  round: number | null;
}

/**
 * Where the pre-game loop stands, read off both pick-ban states and the
 * encounter's own score.
 *
 * The loop runs once per map of the series — map veto -> hero bans -> the map
 * is played and both captains report it — and that report is what opens the
 * next map. The pool only records that a map was PICKED, never that it was
 * played, so the GAMES are what say a position is behind us; keying "settled"
 * off `match != null` marked an unplayed map as finished and printed a 0:0
 * nobody scored.
 */
export function derivePregameLoop(
  encounter: Encounter,
  mapState: PickBanState,
  heroState: PickBanState
): PregameLoopState {
  const statesByKind: Record<PickBanKind, PickBanState> = { map: mapState, hero: heroState };
  // A cancelled session is over for good (the undo is a reset, which makes a
  // new one), so the kind stops applying: no hero rounds for the rest of the
  // series, and a cancelled veto leaves the series in freeplay — exactly the
  // room that never had a veto at all.
  const cancelledKinds = (["map", "hero"] as PickBanKind[]).filter(
    (kind) => statesByKind[kind].session?.status === "cancelled"
  );
  const applicable = (kind: PickBanKind) =>
    !cancelledKinds.includes(kind) &&
    (statesByKind[kind].reason !== "not_configured" || statesByKind[kind].session != null);
  const mapApplies = applicable("map");
  const heroApplies = applicable("hero");

  // Readiness blocks EVERY kind's session at once (one gate per encounter) --
  // any applicable kind reporting "not_ready" means the room as a whole is
  // waiting on captains, never a per-kind state.
  const readiness = mapState.readiness;
  const waitingOnReadiness =
    !(readiness.home && readiness.away) &&
    (["map", "hero"] as PickBanKind[]).some(
      (kind) => applicable(kind) && statesByKind[kind].reason === "not_ready"
    );

  // The FIRST map still merely `picked` (not settled) is the one whose result
  // the loop is waiting on -- `map_report.submit_map_report` flips it the
  // moment both captains agree, and that is what opens the next map's bans.
  const seriesMaps = pickedItemsInOrder(mapState.pool);
  const games = mapState.games ?? [];
  const seriesSummary = mapState.series ?? null;
  const settledAt = (position: number) => {
    const state = gameAtPosition(games, position)?.state;
    return state === "confirmed" || state === "cancelled";
  };
  const pendingIndex = seriesMaps.findIndex((_, index) => !settledAt(index + 1));
  const pendingMap = pendingIndex === -1 ? null : seriesMaps[pendingIndex];
  const pendingRound = pendingIndex === -1 ? null : pendingIndex + 1;
  const mapPhaseOpen = mapApplies && !(mapState.session != null && mapState.is_complete);
  // A hero round counts as settled only when it is the round of the map now
  // awaiting its result: a stale `is_complete` from the PREVIOUS round would
  // otherwise skip this map's bans in the window between its pick and the
  // server appending the round (`pick_ban_session.sync_hero_rounds`, on the
  // next read). With no map phase at all there is no round to align with, so
  // plain completeness is the whole answer.
  const heroRound = highestPoolRound(heroState.pool);
  const heroPhaseOpen =
    heroApplies &&
    !(
      heroState.session != null &&
      heroState.is_complete &&
      (pendingRound == null || (heroRound ?? 0) >= pendingRound)
    );

  // No map veto: after hero bans the captains name the map they played and
  // report its score. That agreed report is the barrier that opens the next
  // hero round.
  const winsNeeded = Math.floor((encounter.best_of ?? 0) / 2) + 1;
  const seriesDecided =
    seriesSummary != null
      ? seriesSummary.complete
      : (encounter.best_of ?? 0) > 0 &&
        ((encounter.score?.home ?? 0) + (encounter.score?.away ?? 0) >= (encounter.best_of ?? 0) ||
          Math.max(encounter.score?.home ?? 0, encounter.score?.away ?? 0) >= winsNeeded);
  const freeplayRound = !mapApplies ? (heroRound ?? 1) : null;
  const awaitingFreeplayReport =
    !mapApplies &&
    !heroPhaseOpen &&
    !seriesDecided &&
    (heroRound ?? 0) > 0 &&
    (heroRound ?? 0) <= (encounter.best_of ?? 0);
  const phase: PregamePhase = mapPhaseOpen
    ? "map"
    : heroPhaseOpen
      ? "hero"
      : pendingMap != null || awaitingFreeplayReport
        ? "report"
        : "done";

  return {
    statesByKind,
    mapApplies,
    heroApplies,
    cancelledKinds,
    // A cancelled session is not an unconfigured room: the room existed, an
    // organizer ended it, and the screen must say that rather than "nothing
    // is set up here".
    unconfigured: !mapApplies && !heroApplies && cancelledKinds.length === 0,
    waitingOnReadiness,
    seriesMaps,
    games,
    pendingIndex,
    pendingMap,
    pendingRound,
    reportRound: pendingRound ?? freeplayRound,
    phase,
    phases: [
      ...(mapApplies ? [{ phase: "map" as const, done: !mapPhaseOpen }] : []),
      ...(heroApplies ? [{ phase: "hero" as const, done: !heroPhaseOpen }] : []),
      ...(mapApplies || awaitingFreeplayReport || phase === "report"
        ? [{ phase: "report" as const, done: phase === "done" }]
        : [])
    ],
    // During the map phase that is the round being vetoed (one past the settled
    // ones); afterwards it is the round whose map is waiting to be played.
    round: pendingRound ?? freeplayRound ?? (mapApplies ? seriesMaps.length + 1 : null)
  };
}

/**
 * The series' history for the header filmstrip. A confirmed game is settled
 * and shows its accepted score; of the rest, the first is the position the
 * loop is waiting on and every later one has not been reached yet.
 */
export function buildSeriesMaps(
  loop: PregameLoopState,
  mapsById: ItemLookup,
  mapName: (itemId: number) => string
): PregameSeriesMap[] {
  return loop.seriesMaps.map((entry, index) => {
    const game = gameAtPosition(loop.games, index + 1);
    return {
      round: index + 1,
      name: mapsById[entry.item_id]?.name ?? mapName(entry.item_id),
      item: mapsById[entry.item_id],
      score: acceptedScore(game),
      state:
        game?.state === "confirmed"
          ? "played"
          : index === loop.pendingIndex
            ? "awaiting"
            : "upcoming"
    };
  });
}

/**
 * The hero board of one map of the series: who banned or protected what, and
 * the final list of everything banned there.
 *
 * Per-side lists come from the SUBMISSIONS, not from the pool: a blind step
 * where both captains ban the same hero projects ONE banned entry carrying one
 * `picked_by`, so reading the board would credit that ban to a single side and
 * leave the other one a ban short of what it actually spent. Bans carried over
 * from an earlier map have no submission of this round at all — they come off
 * the entries, badged with the map they were spent on.
 */
export function heroBoardForRound(
  state: PickBanState,
  round: number | null,
  heroesById: ItemLookup,
  heroName: (itemId: number) => string
): PregameHeroBoard {
  const describe = (
    itemId: number,
    action: "ban" | "protect",
    side: "home" | "away",
    carriedFromRound: number | null
  ): PregameHeroAction => {
    const item = heroesById[itemId];
    return {
      itemId,
      name: item?.name ?? heroName(itemId),
      item,
      role: normalizeRole(item?.type ?? item?.role),
      action,
      side,
      carriedFromRound
    };
  };

  const actions: PregameHeroAction[] = [];
  for (const entry of carriedBanEntries(state.pool, round)) {
    // A system-resolved (roulette) ban projects `picked_by: "decider"`: it
    // belongs to no captain, so it stays out of the side columns and is named
    // only by the final bans list below.
    if (entry.picked_by !== "home" && entry.picked_by !== "away") continue;
    actions.push(describe(entry.item_id, "ban", entry.picked_by, entry.carried_from_round));
  }
  for (const action of ["ban", "protect"] as const) {
    const bySide = appliedItemsBySide(state.sequence, state.submissions, { round, action });
    for (const side of ["home", "away"] as const) {
      for (const item of bySide[side]) actions.push(describe(item.item_id, action, side, null));
    }
  }

  // Every ban in force on this map — carried and engine-rolled ones included,
  // protects never: a protect keeps the hero IN the game.
  const banned = bannedEntries(state.pool, round).map((entry) => {
    const item = heroesById[entry.item_id];
    return {
      itemId: entry.item_id,
      name: item?.name ?? heroName(entry.item_id),
      item,
      role: normalizeRole(item?.type ?? item?.role)
    };
  });

  return { round, actions, banned: groupItemsByRole(banned) };
}

/**
 * The whole series' bans, for the closing screen: by then no map is pending,
 * so the per-map list is empty and the record of what each map was played
 * under would leave the room with the last grid that closed. Round-scoped
 * pools get one block per map; a flat pool has a single set that covered every
 * map, so repeating it per map would invent per-map decisions nobody made.
 */
export function buildHeroRounds(
  state: PickBanState,
  series: PregameSeriesMap[],
  heroesById: ItemLookup,
  heroName: (itemId: number) => string
): PregameHeroRound[] {
  return (
    state.pool.some((entry) => entry.round != null)
      ? series.map((map) => ({
          ...heroBoardForRound(state, map.round, heroesById, heroName),
          mapName: map.name,
          mapItem: map.item
        }))
      : [
          {
            ...heroBoardForRound(state, null, heroesById, heroName),
            mapName: null,
            mapItem: undefined
          }
        ]
    // A map whose only bans were rolled by the engine has no side column to
    // show and still has a lobby to set up.
  ).filter((block) => block.actions.length > 0 || block.banned.length > 0);
}
