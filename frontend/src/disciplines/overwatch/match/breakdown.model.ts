import type { CatalogEntityRead } from "@/types/catalog.types";
import { LogStatsName } from "../stat-names";
import {
  CLASS_ORDER,
  STAT_META,
  activePlayers,
  playerClass,
  playerStat,
  resolveMatchMvpPlacement,
  type MatchStatsPlayer,
  type MatchStatsTeam
} from "./stats";
import { timelineRound, type TimelineFight, type TimelineKill, type TimelineMark, type TimelineSide } from "./timeline";
import { HERO_PLAYED_SECONDS, type HeroTime } from "./view";

type Side = TimelineSide;
type Seats = Pick<MatchStatsTeam, "players">;

/** The six team totals, in the order they are read. */
export const TOTAL_STATS: readonly LogStatsName[] = [
  LogStatsName.Eliminations,
  LogStatsName.Deaths,
  LogStatsName.HeroDamageDealt,
  LogStatsName.HealingDealt,
  LogStatsName.DamageBlocked,
  LogStatsName.UltimatesUsed
];

/** What a role's duel compares, and the one number its players are ranked by before they are paired. */
export const ROLE_STATS: Record<string, readonly LogStatsName[]> = {
  tank: [LogStatsName.HeroDamageDealt, LogStatsName.DamageBlocked, LogStatsName.Deaths],
  damage: [LogStatsName.FinalBlows, LogStatsName.HeroDamageDealt, LogStatsName.Deaths],
  support: [LogStatsName.HealingDealt, LogStatsName.Assists, LogStatsName.Deaths]
};
const ROLE_KEY: Record<string, LogStatsName> = {
  tank: LogStatsName.HeroDamageDealt,
  damage: LogStatsName.HeroDamageDealt,
  support: LogStatsName.HealingDealt
};

export const CARRY_STATS: readonly LogStatsName[] = [
  LogStatsName.HeroDamageDealt,
  LogStatsName.HealingDealt,
  LogStatsName.DamageBlocked,
  LogStatsName.FinalBlows
];

/** The side with the better value (fewer for a reverted stat); a tie has none. */
export function betterSide(name: LogStatsName, home: number, away: number): Side | null {
  if (home === away) return null;
  const higherWins = !STAT_META[name]?.reverted;
  return home > away === higherWins ? "home" : "away";
}

/** The side that holds the higher number of two counts (`fights won`, a role score); a tie has none. */
export const leadingSide = (home: number, away: number): Side | null =>
  home === away ? null : home > away ? "home" : "away";

export const sideOfTeam = (teamId: number | null, homeId: number, awayId: number): Side | null =>
  teamId === homeId ? "home" : teamId === awayId ? "away" : null;

// ── Map flow ────────────────────────────────────────────────────────────────

export interface FlowPoint {
  time: number;
  /** Home final blows minus away final blows up to and including this kill. */
  diff: number;
  kill: TimelineKill;
}

export interface Flow {
  t0: number;
  t1: number;
  points: FlowPoint[];
  /** The y-extent each side needs: the biggest lead it held, at least 2. */
  top: number;
  bottom: number;
  /** Where each later round of the view begins. */
  starts: { round: number; time: number }[];
}

const byTime = <T extends { time: number }>(items: readonly T[]) => [...items].sort((a, b) => a.time - b.time);

/**
 * The running final-blow difference of the kills in view. A kill whose side is unknown moves nobody's count (and
 * draws no point). `null` when there are no kills at all.
 */
export function readFlow(
  kills: readonly TimelineKill[],
  marks: readonly TimelineMark[],
  homeId: number,
  awayId: number
): Flow | null {
  if (kills.length === 0) return null;
  const sorted = byTime(kills);
  const points: FlowPoint[] = [];
  let diff = 0;
  for (const kill of sorted) {
    const side = sideOfTeam(kill.killer_team_id, homeId, awayId);
    if (!side) continue;
    diff += side === "home" ? 1 : -1;
    points.push({ time: kill.time, diff, kill });
  }
  const events = [...sorted, ...marks];
  const times = events.map((event) => event.time);
  const firstOf = new Map<number, number>();
  for (const event of events) {
    const round = timelineRound(event.round);
    firstOf.set(round, Math.min(firstOf.get(round) ?? Infinity, event.time));
  }
  const starts = [...firstOf.entries()]
    .sort((a, b) => a[0] - b[0])
    .slice(1)
    .map(([round, time]) => ({ round, time: time - 5 }));
  return {
    t0: Math.max(0, Math.min(...times) - 10),
    t1: Math.max(...times) + 10,
    points,
    top: Math.max(2, ...points.map((point) => point.diff)),
    bottom: Math.max(2, ...points.map((point) => -point.diff)),
    starts
  };
}

// ── Moments ─────────────────────────────────────────────────────────────────

export interface FightSummary {
  won: Record<Side, number>;
  /** Fights nobody won, or whose tally is unknown. */
  draws: number;
  first: Record<Side, number>;
  /** Percent of the fights a side opened that it also won; `null` for a side that never opened one. */
  conversion: Record<Side, number | null>;
  /** The fight with the most kills (then the widest margin) among those with a known tally. */
  biggest: TimelineFight | null;
}

const tally = (fight: TimelineFight) => (fight.home ?? 0) + (fight.away ?? 0);
const margin = (fight: TimelineFight) => Math.abs((fight.home ?? 0) - (fight.away ?? 0));

export function summarizeFights(fights: readonly TimelineFight[]): FightSummary {
  const count = (pick: (fight: TimelineFight) => boolean) => fights.filter(pick).length;
  const won = { home: count((f) => f.winner === "home"), away: count((f) => f.winner === "away") };
  const first = { home: count((f) => f.first === "home"), away: count((f) => f.first === "away") };
  const conversion = (side: Side) =>
    first[side] ? Math.round((count((f) => f.first === side && f.winner === side) / first[side]) * 100) : null;
  const biggest = fights
    .filter((fight) => fight.home != null)
    .reduce<TimelineFight | null>(
      (best, fight) =>
        !best || tally(fight) > tally(best) || (tally(fight) === tally(best) && margin(fight) > margin(best))
          ? fight
          : best,
      null
    );
  return {
    won,
    draws: fights.length - won.home - won.away,
    first,
    conversion: { home: conversion("home"), away: conversion("away") },
    biggest
  };
}

export interface Run {
  /** Kills in a row. */
  n: number;
  from: number;
  to: number;
}

/**
 * Each side's longest run of kills with no reply. An unknown-side kill belongs to no run and ends the one before it;
 * the earlier run wins a tie.
 */
export function bestRuns(kills: readonly TimelineKill[], homeId: number, awayId: number): Record<Side, Run | null> {
  const best: Record<Side, Run | null> = { home: null, away: null };
  // Widened on purpose: control flow would otherwise pin the loop's view of `open` to its `null` initialiser.
  let open = null as { side: Side; run: Run } | null;
  for (const kill of byTime(kills)) {
    const side = sideOfTeam(kill.killer_team_id, homeId, awayId);
    if (!side) {
      open = null;
      continue;
    }
    if (open?.side === side) {
      open.run = { ...open.run, n: open.run.n + 1, to: kill.time };
    } else {
      open = { side, run: { n: 1, from: kill.time, to: kill.time } };
    }
    const current = best[side];
    if (!current || open.run.n > current.n) best[side] = open.run;
  }
  return best;
}

// ── Role duels ──────────────────────────────────────────────────────────────

export interface DuelStat {
  name: LogStatsName;
  home: number;
  away: number;
  /** `null` on a tie, and whenever a side has no player to compare. */
  winner: Side | null;
}

export interface Duel {
  home: MatchStatsPlayer | null;
  away: MatchStatsPlayer | null;
  stats: DuelStat[];
  wins: Record<Side, number>;
}

export interface RoleDuels {
  role: string;
  duels: Duel[];
  /** Stats won across the role's duels. */
  score: Record<Side, number>;
}

/**
 * Same class meets same class, best against best by the class's key stat. Unequal counts leave the surplus
 * players against an empty side (nothing to win there). Roles nobody played are left out.
 */
export function roleDuels(home: Seats, away: Seats, round: number): RoleDuels[] {
  const out: RoleDuels[] = [];
  for (const role of CLASS_ORDER) {
    const key = ROLE_KEY[role];
    const pick = (team: Seats) =>
      activePlayers(team, round)
        .filter((player) => playerClass(player, round) === role)
        .sort((a, b) => playerStat(b, round, key) - playerStat(a, round, key));
    const h = pick(home);
    const a = pick(away);
    const score = { home: 0, away: 0 };
    const duels = Array.from({ length: Math.max(h.length, a.length) }, (_, i): Duel => {
      const ph = h[i] ?? null;
      const pa = a[i] ?? null;
      const wins = { home: 0, away: 0 };
      const stats = ROLE_STATS[role].map((name): DuelStat => {
        const hv = ph ? playerStat(ph, round, name) : 0;
        const av = pa ? playerStat(pa, round, name) : 0;
        const winner = ph && pa ? betterSide(name, hv, av) : null;
        if (winner) wins[winner] += 1;
        return { name, home: hv, away: av, winner };
      });
      score.home += wins.home;
      score.away += wins.away;
      return { home: ph, away: pa, stats, wins };
    });
    if (duels.length) out.push({ role, duels, score });
  }
  return out;
}

/** The duel a player played, from his own side's view; `null` when he faced nobody. */
export function duelOf(
  roles: readonly RoleDuels[],
  player: MatchStatsPlayer
): { opponent: MatchStatsPlayer; mine: number; theirs: number } | null {
  for (const { duels } of roles) {
    for (const duel of duels) {
      if (duel.home === player && duel.away) return { opponent: duel.away, mine: duel.wins.home, theirs: duel.wins.away };
      if (duel.away === player && duel.home) return { opponent: duel.home, mine: duel.wins.away, theirs: duel.wins.home };
    }
  }
  return null;
}

// ── Who carried ─────────────────────────────────────────────────────────────

export interface CarryShare {
  player: MatchStatsPlayer;
  value: number;
  /** 0–1 of the team total. */
  share: number;
}

/** Each player's share of a team's total of a stat; players with nothing are left out, biggest first. */
export function carryShares(team: Seats, round: number, name: LogStatsName): { shares: CarryShare[]; total: number } {
  const rows = activePlayers(team, round)
    .map((player) => ({ player, value: playerStat(player, round, name) }))
    .filter((row) => row.value > 0)
    .sort((a, b) => b.value - a.value);
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  return { shares: rows.map((row) => ({ ...row, share: row.value / total })), total };
}

/** Seat-colour strength of the n-th segment of a share bar. */
const CARRY_MIX = [100, 76, 58, 44, 34, 28];
export const carryMix = (index: number) => CARRY_MIX[Math.min(index, CARRY_MIX.length - 1)];

/** What a share segment can carry: name and percent when roomy, the percent when narrow, nothing in a sliver. */
export const shareLabel = (share: number): "full" | "pct" | "none" =>
  share >= 0.2 ? "full" : share >= 0.09 ? "pct" : "none";

// ── Player of the map ───────────────────────────────────────────────────────

export interface Mvp {
  player: MatchStatsPlayer;
  side: Side;
  /** The other side's best-placed player. */
  rival: { player: MatchStatsPlayer; place: number } | null;
}

const FIGURE_FALLBACK: readonly LogStatsName[] = [
  LogStatsName.Eliminations,
  LogStatsName.FinalBlows,
  LogStatsName.HeroDamageDealt,
  LogStatsName.HealingDealt,
  LogStatsName.DamageBlocked
];

/** The player placed first by impact in `round`, and the other side's best placement. `null` without one. */
export function findMvp(home: Seats, away: Seats, round: number): Mvp | null {
  const ranked = (["home", "away"] as const).flatMap((side) =>
    activePlayers(side === "home" ? home : away, round).flatMap((player) => {
      const place = resolveMatchMvpPlacement(player, round);
      return place != null && place > 0 ? [{ player, side, place }] : [];
    })
  );
  const top = ranked.find((entry) => entry.place === 1);
  if (!top) return null;
  const rival = ranked
    .filter((entry) => entry.side !== top.side)
    .sort((a, b) => a.place - b.place)[0];
  return { player: top.player, side: top.side, rival: rival ? { player: rival.player, place: rival.place } : null };
}

/** Two numbers the player did something with (his class's first, never a zero or a reverted stat). */
export function mvpFigures(player: MatchStatsPlayer, round: number): LogStatsName[] {
  const role = playerClass(player, round);
  const wanted = [...(ROLE_STATS[role ?? ""] ?? []), ...FIGURE_FALLBACK].filter((name) => !STAT_META[name]?.reverted);
  return [...new Set(wanted)].filter((name) => playerStat(player, round, name) > 0).slice(0, 2);
}

// ── Lineups ─────────────────────────────────────────────────────────────────

/** The segments a lineup has a column for: one round, or every round with data (the whole map when it has none). */
export function lineupColumns(rounds: readonly number[], round: number): number[] {
  if (round !== 0) return [round];
  const real = rounds.filter((value) => value > 0);
  return real.length ? real : [0];
}

export interface LineupCell {
  main: HeroTime;
  /** Up to two other characters played at least `HERO_PLAYED_SECONDS`. */
  extras: CatalogEntityRead[];
  /** Every character of the segment, longest first. */
  all: HeroTime[];
  /** The main character of the column before when it differs. */
  swappedFrom: CatalogEntityRead | null;
}

/** One player's cells across `columns`; `null` where he was not observed on a character. */
export function lineupRow(player: MatchStatsPlayer, columns: readonly number[]): (LineupCell | null)[] {
  let previous: CatalogEntityRead | null = null;
  return columns.map((column) => {
    const all = (player.heroTimes[column] ?? []).filter((hero) => hero.seconds > 0);
    if (all.length === 0) {
      previous = null;
      return null;
    }
    const [main] = all;
    const swappedFrom = previous && previous.id !== main.entity.id ? previous : null;
    previous = main.entity;
    return {
      main,
      extras: all
        .slice(1)
        .filter((hero) => hero.seconds >= HERO_PLAYED_SECONDS)
        .slice(0, 2)
        .map((hero) => hero.entity),
      all,
      swappedFrom
    };
  });
}
