import type { CatalogEntityRead } from "@/types/catalog.types";
import type { MatchWithStats } from "@/types/encounter.types";
import { LogStatsName } from "../stat-names";
import { owMatchView, type OwPlayer, type OwTeam } from "./view";

// ─── Series statistics aggregation ──────────────────────────────────────────
//
// Per-map stats arrive as `segment → stat code → value` with segment `0` = whole map. To describe a SERIES we
// fold every map's segment-0 row into one synthetic segment-0 row per player, then re-derive the ratio stats
// with the parser's own formulas (`stats-service` → `_calculate_and_add_derived_stats`) instead of averaging
// per-map ratios, which would weight a 3-minute map the same as a 12-minute one.

/** Summed across maps. */
const ADDITIVE_STATS: readonly LogStatsName[] = [
  LogStatsName.Eliminations,
  LogStatsName.FinalBlows,
  LogStatsName.Deaths,
  LogStatsName.Assists,
  LogStatsName.OffensiveAssists,
  LogStatsName.DefensiveAssists,
  LogStatsName.AllDamageDealt,
  LogStatsName.BarrierDamageDealt,
  LogStatsName.HeroDamageDealt,
  LogStatsName.HealingDealt,
  LogStatsName.HealingReceived,
  LogStatsName.SelfHealing,
  LogStatsName.DamageTaken,
  LogStatsName.DamageBlocked,
  LogStatsName.UltimatesEarned,
  LogStatsName.UltimatesUsed,
  LogStatsName.Multikills,
  LogStatsName.SoloKills,
  LogStatsName.ObjectiveKills,
  LogStatsName.EnvironmentalKills,
  LogStatsName.EnvironmentalDeaths,
  LogStatsName.CriticalHits,
  LogStatsName.ScopedCriticalHitKills,
  LogStatsName.ShotsFired,
  LogStatsName.ShotsHit,
  LogStatsName.ShotsMissed,
  LogStatsName.ScopedShotsFired,
  LogStatsName.ScopedShotsHit,
  LogStatsName.HeroTimePlayed,
  LogStatsName.FirstPicks,
  LogStatsName.FirstDeaths,
  LogStatsName.UltimateKills,
  LogStatsName.SupportKills
];

/** A series' "best multikill" is the best single map's, not their sum. */
const MAX_STATS: readonly LogStatsName[] = [LogStatsName.MultikillBest];

/**
 * Ratio stats recomputed from the summed numerator/denominator. `stats-service`
 * divides by `denominator.replace(0, 1)`, so a zero denominator yields the bare
 * numerator — mirrored here so a series row and a map row agree.
 */
const RATIO_STATS: readonly { name: LogStatsName; over: LogStatsName; by: LogStatsName }[] = [
  { name: LogStatsName.KD, over: LogStatsName.Eliminations, by: LogStatsName.Deaths },
  { name: LogStatsName.FBE, over: LogStatsName.FinalBlows, by: LogStatsName.Eliminations },
  { name: LogStatsName.DamageFB, over: LogStatsName.HeroDamageDealt, by: LogStatsName.FinalBlows }
];

/** Accuracy percentages are fractions (0..1) recomputed from shot counts. */
const ACCURACY_STATS: readonly { name: LogStatsName; hit: LogStatsName; fired: LogStatsName }[] = [
  { name: LogStatsName.WeaponAccuracy, hit: LogStatsName.ShotsHit, fired: LogStatsName.ShotsFired },
  {
    name: LogStatsName.CriticalHitAccuracy,
    hit: LogStatsName.CriticalHits,
    fired: LogStatsName.ShotsHit
  },
  {
    name: LogStatsName.ScopedAccuracy,
    hit: LogStatsName.ScopedShotsHit,
    fired: LogStatsName.ScopedShotsFired
  }
];

/**
 * Stats no honest series value exists for, so they are left absent (rendered as
 * `—`) rather than guessed: the per-map `impact_*`/`overperformance_*`/contribution facts do not add up across
 * maps (the series placement is derived separately from them), and `scoped_critical_hit_accuracy` needs a
 * scoped-critical-HITS counter the API does not expose.
 */
const SERIES_UNAVAILABLE_STATS: readonly LogStatsName[] = [
  LogStatsName.ImpactPoints,
  LogStatsName.ImpactRank,
  LogStatsName.OverperformanceScore,
  LogStatsName.ScopedCriticalHitAccuracy,
  LogStatsName.Winrate
];

type StatRow = Record<string, number>;

const WHOLE_MAP_ROUND = 0;

function readStat(row: StatRow, name: LogStatsName): number {
  const value = row[name];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** `stats-service` divides by `denominator.replace(0, 1)`. */
function ratio(numerator: number, denominator: number): number {
  return numerator / (denominator === 0 ? 1 : denominator);
}

function foldStatRow(target: StatRow, source: StatRow): void {
  for (const name of ADDITIVE_STATS) {
    const value = source[name];
    if (typeof value === "number" && Number.isFinite(value)) {
      target[name] = (target[name] ?? 0) + value;
    }
  }
  for (const name of MAX_STATS) {
    const value = source[name];
    if (typeof value === "number" && Number.isFinite(value)) {
      target[name] = Math.max(target[name] ?? 0, value);
    }
  }
}

function deriveStatRow(row: StatRow): void {
  // `assists` is itself derived; recompute it when the map rows only carried
  // the offensive/defensive split.
  const splitAssists =
    readStat(row, LogStatsName.OffensiveAssists) + readStat(row, LogStatsName.DefensiveAssists);
  if (row[LogStatsName.Assists] == null && splitAssists > 0) {
    row[LogStatsName.Assists] = splitAssists;
  }

  for (const { name, over, by } of RATIO_STATS) {
    if (row[over] == null && row[by] == null) continue;
    row[name] = ratio(readStat(row, over), readStat(row, by));
  }
  row[LogStatsName.KDA] = ratio(
    readStat(row, LogStatsName.Eliminations) + readStat(row, LogStatsName.Assists),
    readStat(row, LogStatsName.Deaths)
  );
  row[LogStatsName.DamageDelta] =
    readStat(row, LogStatsName.HeroDamageDealt) - readStat(row, LogStatsName.DamageTaken);

  for (const { name, hit, fired } of ACCURACY_STATS) {
    const shots = readStat(row, fired);
    // Leave absent rather than emit 0% for a hero that never fires a weapon.
    if (shots <= 0) {
      delete row[name];
      continue;
    }
    row[name] = readStat(row, hit) / shots;
  }

  for (const name of SERIES_UNAVAILABLE_STATS) {
    delete row[name];
  }
}

interface SeriesPlayerMeta {
  /** Observations this participation's player appears in, even without a hero fact. */
  mapsPlayed: number;
  /** 1-based series MVP placement (competition rank of the playtime-weighted mean of map `impact_points`). */
  seriesPlacement: number | null;
}

interface SeriesParticipation extends OwTeam {
  /** Player metadata is scoped to this participation, not the source roster. */
  meta: Record<number, SeriesPlayerMeta>;
}

export interface SeriesAggregate {
  /** Observed participations, including retired ones; never current roster seats. */
  participations: SeriesParticipation[];
  mapsCounted: number;
  /** The round key the folded observations expose. */
  round: number;
}

interface Entry {
  player: OwPlayer;
  stats: StatRow;
  heroes: Map<number, CatalogEntityRead>;
  maps: number;
  /** Σ map `impact_points` × seconds played, over the maps that scored the player. */
  weightedPoints: number;
  /** Σ seconds played over those maps. */
  seconds: number;
}

function foldPlayer(accumulator: Map<number, Entry>, player: OwPlayer): void {
  const heroesThisMap = player.heroes?.[WHOLE_MAP_ROUND] ?? [];
  const existing = accumulator.get(player.workspace_member_id);
  const entry = existing ?? {
    player,
    stats: {} as StatRow,
    heroes: new Map<number, CatalogEntityRead>(),
    maps: 0,
    weightedPoints: 0,
    seconds: 0
  };

  const mapRow = player.stats?.[WHOLE_MAP_ROUND] ?? {};
  foldStatRow(entry.stats, mapRow);
  const points = mapRow[LogStatsName.ImpactPoints];
  const seconds = readStat(mapRow, LogStatsName.HeroTimePlayed);
  if (typeof points === "number" && Number.isFinite(points) && seconds > 0) {
    entry.weightedPoints += points * seconds;
    entry.seconds += seconds;
  }
  for (const hero of heroesThisMap) {
    if (!entry.heroes.has(hero.id)) entry.heroes.set(hero.id, hero);
  }
  entry.maps += 1;

  if (!existing) accumulator.set(player.workspace_member_id, entry);
}

function buildParticipation(
  base: OwTeam,
  accumulator: Map<number, Entry>
): {
  participation: SeriesParticipation;
  rows: { id: number; mean: number | null; maps: number }[];
} {
  const players: OwPlayer[] = [];
  const rows: { id: number; mean: number | null; maps: number }[] = [];

  for (const entry of accumulator.values()) {
    if (Object.keys(entry.stats).length > 0) deriveStatRow(entry.stats);
    players.push({
      ...entry.player,
      stats: { [WHOLE_MAP_ROUND]: entry.stats },
      heroes: { [WHOLE_MAP_ROUND]: Array.from(entry.heroes.values()) },
      // Per-map stints do not add up into one series stint: the series view draws `heroes` only.
      heroTimes: {}
    });
    rows.push({
      id: entry.player.workspace_member_id,
      mean: entry.seconds > 0 ? entry.weightedPoints / entry.seconds : null,
      maps: entry.maps
    });
  }

  return { participation: { ...base, players, meta: {} }, rows };
}

/**
 * Fold every observation by its native participation and workspace-member
 * identity. Source teams, current slots and game order do not decide which
 * facts count; the participation snapshot remains the statistics heading. A
 * match that is not a duel has no Overwatch view and contributes nothing.
 */
export function aggregateSeriesStats(matches: MatchWithStats[]): SeriesAggregate | null {
  const groups = new Map<number, { base: OwTeam; players: Map<number, Entry> }>();

  for (const match of matches) {
    const view = owMatchView(match);
    if (!view) continue;
    for (const participation of [view.home, view.away]) {
      let group = groups.get(participation.id);
      if (!group) {
        group = { base: participation, players: new Map() };
        groups.set(participation.id, group);
      }
      for (const player of participation.players) foldPlayer(group.players, player);
    }
  }

  if (groups.size === 0) return null;

  const folded = Array.from(groups.values(), ({ base, players }) =>
    buildParticipation(base, players)
  );
  const means = folded.flatMap(({ rows }) => rows.flatMap((row) => (row.mean == null ? [] : [row.mean])));

  for (const { participation, rows } of folded) {
    for (const { id, maps, mean } of rows) {
      participation.meta[id] = {
        mapsPlayed: maps,
        // Competition rank: ties share a place.
        seriesPlacement: mean == null ? null : 1 + means.filter((other) => other > mean).length
      };
    }
    for (const player of participation.players) {
      const placement = participation.meta[player.workspace_member_id]?.seriesPlacement;
      const row = player.stats[WHOLE_MAP_ROUND];
      if (placement != null) row[LogStatsName.ImpactRank] = placement;
    }
  }

  return {
    participations: folded.map(({ participation }) => participation),
    mapsCounted: matches.length,
    round: WHOLE_MAP_ROUND
  };
}
