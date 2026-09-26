import { normalizeRole } from "@/lib/roster/player-role";
import {
  acceptedScore,
  gameAtPosition,
  highestPoolRound,
  pickedItemsInOrder
} from "@/components/pick-ban/pick-ban-model";
import type { PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import type { Encounter } from "@/types/encounter.types";
import type { PickBanEntry, PickBanGame, PickBanKind, PickBanState } from "@/types/tournament.types";

import type { PregameHeroAction, PregameHeroRound } from "./PregameHeroBans";
import type { PregamePhase, PregamePhaseStatus, PregameSeriesMap } from "./PregameHeader";

type ItemLookup = Record<number, PickBanItemLike | undefined>;

export interface PregameLoopState {
  statesByKind: Record<PickBanKind, PickBanState>;
  /** Something WOULD open for this kind once teams/rules/readiness allow it. */
  mapApplies: boolean;
  heroApplies: boolean;
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
  const applicable = (kind: PickBanKind) =>
    statesByKind[kind].reason !== "not_configured" || statesByKind[kind].session != null;
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
        Math.max(encounter.score?.home ?? 0, encounter.score?.away ?? 0) >= winsNeeded;
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
    unconfigured: !mapApplies && !heroApplies,
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
 * The hero bans that apply to one map of the series, resolved against the
 * catalog. The room shows one phase at a time, so once the hero grid closes
 * nothing on screen names what was banned -- which is precisely when the
 * captains have to enter it into the game lobby. A flat (round-less) hero pool
 * has one set of bans for the whole series, so it applies to every map.
 */
export function heroActionsForRound(
  pool: PickBanEntry[],
  round: number | null,
  heroesById: ItemLookup,
  heroName: (itemId: number) => string
): PregameHeroAction[] {
  return pool
    .filter(
      (entry) =>
        (round == null ? entry.round == null : entry.round == null || entry.round === round) &&
        (entry.status === "banned" || entry.status === "protected")
    )
    .map((entry) => {
      const item = heroesById[entry.item_id];
      const side = entry.status === "banned" ? entry.picked_by : entry.protected_by;
      return {
        itemId: entry.item_id,
        name: item?.name ?? heroName(entry.item_id),
        item,
        role: normalizeRole(item?.type ?? item?.role),
        action: entry.status === "banned" ? ("ban" as const) : ("protect" as const),
        // `picked_by` also carries `"decider"`, which no ban can be.
        side: side === "away" ? ("away" as const) : ("home" as const)
      };
    });
}

/**
 * The whole series' bans, for the closing screen: by then no map is pending,
 * so the per-map list is empty and the record of what each map was played
 * under would leave the room with the last grid that closed. Round-scoped
 * pools get one block per map; a flat pool has a single set that covered every
 * map, so repeating it per map would invent per-map decisions nobody made.
 */
export function buildHeroRounds(
  pool: PickBanEntry[],
  series: PregameSeriesMap[],
  heroesById: ItemLookup,
  heroName: (itemId: number) => string
): PregameHeroRound[] {
  return (
    pool.some((entry) => entry.round != null)
      ? series.map((map) => ({
          round: map.round,
          mapName: map.name,
          mapItem: map.item,
          actions: heroActionsForRound(pool, map.round, heroesById, heroName)
        }))
      : [
          {
            round: null,
            mapName: null,
            mapItem: undefined,
            actions: heroActionsForRound(pool, null, heroesById, heroName)
          }
        ]
  ).filter((block) => block.actions.length > 0);
}
