import { getEncounterWinner } from "@/lib/encounter/status";
import type { HeroBan, MapBan } from "@/lib/tournament/insights-query";
import type { Encounter, EncounterTeam } from "@/types/encounter.types";
import type { TournamentPlayerStatKey } from "@/types/tournament.types";

/**
 * Values are each player's per-map average over the tournament's logged maps, ranked across every player who has
 * one; `performance` is the MVP place on a map, 1 = best of ten.
 */
export const STAT_META: Record<
  TournamentPlayerStatKey,
  { lowerIsBetter: boolean; digits: number }
> = {
  performance: { lowerIsBetter: true, digits: 2 },
  kda: { lowerIsBetter: false, digits: 2 },
  eliminations: { lowerIsBetter: false, digits: 1 },
  deaths: { lowerIsBetter: true, digits: 1 },
  assists: { lowerIsBetter: false, digits: 1 },
  hero_damage_dealt: { lowerIsBetter: false, digits: 0 },
  damage_delta: { lowerIsBetter: false, digits: 0 }
};

export const ROLE_ORDER = ["tank", "damage", "support"] as const;
export type TournamentRole = (typeof ROLE_ORDER)[number];
export const isTournamentRole = (role: string | null): role is TournamentRole =>
  role !== null && (ROLE_ORDER as readonly string[]).includes(role);

/** Sub-roles (`damage_main`, `support_flex`) fold into their role. */
export const baseRole = (role: string | null | undefined) => (role ? role.split("_")[0] : null);

/** "01", "02"… — the ranked-column voice (DESIGN §8). */
export const rankLabel = (index: number) => String(index + 1).padStart(2, "0");

/** One series from a team's seat: its score first, the opponent's second. */
export interface TeamSeries {
  mine: EncounterTeam;
  theirs: EncounterTeam;
  result: "w" | "l" | "d";
}

export function seriesFor(encounter: Encounter, teamId: number): TeamSeries | null {
  const mine = encounter.teams.find((seat) => seat.team_id === teamId);
  const theirs = encounter.teams.find((seat) => seat.team_id !== teamId);
  if (!mine || !theirs) return null;
  const winner = getEncounterWinner(encounter);
  return { mine, theirs, result: winner == null ? "d" : winner === mine.slot ? "w" : "l" };
}

/** The prefix of `items` whose weight comes closest to half, and how far the two runs still differ. */
function cutInHalf<T>(items: readonly T[], weight: (item: T) => number) {
  const total = items.reduce((sum, item) => sum + weight(item), 0);
  let cut = 0;
  let gap = Infinity;
  let prefix = 0;
  for (let index = 0; index <= items.length; index++) {
    if (Math.abs(total - 2 * prefix) < gap) {
      gap = Math.abs(total - 2 * prefix);
      cut = index;
    }
    if (index < items.length) prefix += weight(items[index]);
  }
  return { left: items.slice(0, cut), right: items.slice(cut), gap };
}

/**
 * Cards in reading order laid out as two columns of near-equal weight (≈ height): the left column is a prefix, so a
 * phone, which stacks them, still reads them in order. When the cards cannot be cut evenly (five equal rounds), the last
 * one leaves the columns and runs full width under them. Feeds `CardColumns`, whose stretch covers what is left.
 */
export function balanceColumns<T>(
  items: readonly T[],
  weight: (item: T) => number
): { left: T[]; right: T[]; tail: T | null } {
  const whole = cutInHalf(items, weight);
  if (items.length < 3) return { left: whole.left, right: whole.right, tail: null };
  const head = cutInHalf(items.slice(0, -1), weight);
  return head.gap < whole.gap
    ? { left: head.left, right: head.right, tail: items[items.length - 1] }
    : { left: whole.left, right: whole.right, tail: null };
}

/** The bans aggregated over the series the caller keeps. */
export type TournamentBans = {
  /** Series that ran a hero ban session. */
  series: number;
  /** One row per hero: how often a team chose to ban it, on the first map (blind) and later (targeted). */
  heroes: { id: number; bans: number; series: number; blind: number; targeted: number }[];
  /** Tournament player ids whose heroes the opponents targeted, most targeted first. */
  targets: { playerId: number; bans: number; heroes: { id: number; bans: number }[] }[];
  /** Per map: how often it was struck from the pool and how often it was chosen. */
  maps: { id: number; banned: number; picked: number }[];
  totalHeroBans: number;
};

/** The bans of the series `keep` admits (all of them by default), aggregated; `null` when there are none. */
export function aggregateBans(
  heroBans: readonly HeroBan[],
  mapBans: readonly MapBan[],
  keep: (encounterId: number) => boolean = () => true
): TournamentBans | null {
  const heroes = new Map<
    number,
    { bans: number; series: Set<number>; blind: number; targeted: number }
  >();
  const targets = new Map<number, Map<number, number>>();
  const maps = new Map<number, { banned: number; picked: number }>();
  const series = new Set<number>();
  let totalHeroBans = 0;
  for (const ban of heroBans) {
    if (!keep(ban.encounterId)) continue;
    series.add(ban.encounterId);
    totalHeroBans += 1;
    const row = heroes.get(ban.heroId) ?? {
      bans: 0,
      series: new Set<number>(),
      blind: 0,
      targeted: 0
    };
    row.bans += 1;
    row.series.add(ban.encounterId);
    if (ban.firstMap) row.blind += 1;
    else row.targeted += 1;
    heroes.set(ban.heroId, row);
    if (ban.targetPlayerId != null) {
      const byHero = targets.get(ban.targetPlayerId) ?? new Map<number, number>();
      byHero.set(ban.heroId, (byHero.get(ban.heroId) ?? 0) + 1);
      targets.set(ban.targetPlayerId, byHero);
    }
  }
  for (const ban of mapBans) {
    if (!keep(ban.encounterId)) continue;
    const row = maps.get(ban.mapId) ?? { banned: 0, picked: 0 };
    if (ban.picked) row.picked += 1;
    else row.banned += 1;
    maps.set(ban.mapId, row);
  }
  if (totalHeroBans === 0 && maps.size === 0) return null;
  return {
    series: series.size,
    totalHeroBans,
    heroes: [...heroes]
      .map(([id, row]) => ({
        id,
        bans: row.bans,
        series: row.series.size,
        blind: row.blind,
        targeted: row.targeted
      }))
      .sort((a, b) => b.bans - a.bans),
    targets: [...targets]
      .map(([playerId, byHero]) => ({
        playerId,
        bans: [...byHero.values()].reduce((sum, n) => sum + n, 0),
        heroes: [...byHero].map(([id, bans]) => ({ id, bans })).sort((a, b) => b.bans - a.bans)
      }))
      .sort((a, b) => b.bans - a.bans),
    maps: [...maps]
      .map(([id, row]) => ({ id, ...row }))
      .sort((a, b) => b.picked - a.picked || a.banned - b.banned)
  };
}

/**
 * Every targeted ban names one opponent player, and every opponent player takes one per map, so a raw count only
 * measures maps played. What the anti-one-trick bans DO reveal is how often it was the same hero: a player whose
 * one hero took most of their bans is the one-trick the format was built against.
 */
export interface OneTrick {
  playerId: number;
  heroId: number;
  heroBans: number;
  bans: number;
  share: number;
}

export function oneTricks(bans: TournamentBans | null, minBans = 5): OneTrick[] {
  return (bans?.targets ?? [])
    .filter((row) => row.bans >= minBans && row.heroes.length > 0)
    .map((row) => ({
      playerId: row.playerId,
      heroId: row.heroes[0].id,
      heroBans: row.heroes[0].bans,
      bans: row.bans,
      share: row.heroes[0].bans / row.bans
    }))
    .sort((a, b) => b.share - a.share || b.heroBans - a.heroBans);
}
