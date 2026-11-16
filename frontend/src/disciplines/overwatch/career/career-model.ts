import type { CharacterWithUserStats, CareerAccount, CareerCharacter, CareerQueue} from "@/types/user.types";

import { LogStatsName } from "../stat-names";
import { heroWinrate, isRevertedStat } from "../character/utils";

/** The game's own rate keys against the keys of our match facts (`LogStatsName`). */
const CAREER_STAT = {
  eliminations: LogStatsName.Eliminations,
  deaths: LogStatsName.Deaths,
  hero_damage_done: LogStatsName.HeroDamageDealt,
  healing_done: LogStatsName.HealingDealt
} as const;

type CompareRate = keyof typeof CAREER_STAT;

/** Below this many healing points per 10 minutes the player does not heal: the tiles show damage instead. */
const HEALING_FLOOR = 100;

export const queueOf = (
  account: CareerAccount,
  platform: string | null,
  queue: "competitive" | "quickplay"
): CareerQueue | undefined =>
  account.queues.find((candidate) => candidate.platform === platform && candidate.queue === queue);

/** An account with at least one queue to draw: a closed or uncollected profile has none. */
export const hasCareerData = (account: CareerAccount) => account.queues.length > 0;

/** Primary first, then the order the server sent. */
export const primaryFirst = (accounts: CareerAccount[]) =>
  [...accounts].sort((a, b) => Number(b.is_primary) - Number(a.is_primary));

/** The account that speaks for the player in a compact view: the primary one with data, else any with data. */
export const mainDataAccount = (accounts: CareerAccount[]) => primaryFirst(accounts).find(hasCareerData);

export type AccountState = "primary" | "ok" | "private" | "notFound" | "pending" | "error";

/** What an account's chip says. A closed profile is closed whatever the last collection status was. */
export const accountState = (account: CareerAccount): AccountState => {
  if (account.profile?.is_public === false || account.status === "private") return "private";
  if (account.status === "not_found") return "notFound";
  if (account.status === "error") return "error";
  if (account.status === "ok") return account.is_primary ? "primary" : "ok";
  // Never collected (null, pending), or switched off.
  return "pending";
};

export const platformsOf = (account: CareerAccount): string[] => [
  ...new Set(account.queues.flatMap((queue) => (queue.platform ? [queue.platform] : [])))
];

/** PC unless the account only has console data. */
export const defaultPlatform = (account: CareerAccount): string | null => {
  const platforms = platformsOf(account);
  return platforms.includes("pc") ? "pc" : (platforms[0] ?? null);
};

/** The one figure a role's tiles show next to eliminations and deaths: healing for a healer, damage otherwise. */
export const outputRate = (rates: Record<string, number> | undefined, role: string | null): "healing_done" | "hero_damage_done" =>
  role === "support" && (rates?.healing_done ?? 0) >= HEALING_FLOOR ? "healing_done" : "hero_damage_done";

export const queueOutputRate = (queue: CareerQueue): "healing_done" | "hero_damage_done" =>
  (queue.rates.healing_done ?? 0) >= HEALING_FLOOR ? "healing_done" : "hero_damage_done";

export interface HeroComparison {
  rate: CompareRate | "winrate";
  ladder: number | null;
  ours: number | null;
  /** `true` when our value is better than the ladder's, `false` when worse, `null` when equal or unknown. */
  better: boolean | null;
}

/** Two values count as equal at this precision: the game reports rates to two decimals. */
const same = (a: number, b: number) => Math.abs(a - b) < 0.005;

const judge = (ladder: number | null, ours: number | null, lowerIsBetter: boolean): boolean | null => {
  if (ladder == null || ours == null || same(ladder, ours)) return null;
  return lowerIsBetter ? ours < ladder : ours > ladder;
};

const oursRate = (hero: CharacterWithUserStats, rate: CompareRate): number | null => {
  const stat = hero.stats.find((entry) => entry.name === CAREER_STAT[rate]);
  return stat && Number.isFinite(stat.avg_10) ? stat.avg_10 : null;
};

/** One hero: the ladder's figures against our tournaments', for the rows the spec names. */
export const compareHero = (ladder: CareerCharacter, ours: CharacterWithUserStats): HeroComparison[] => {
  const rows: HeroComparison[] = [];
  const winrate = ladder.winrate;
  const ourWinrate = heroWinrate(ours);
  rows.push({ rate: "winrate", ladder: winrate, ours: ourWinrate, better: judge(winrate, ourWinrate, false) });
  const rates: CompareRate[] = [
    "eliminations",
    "deaths",
    outputRate(ladder.rates, ladder.role)
  ];
  for (const rate of rates) {
    const l = ladder.rates?.[rate] ?? null;
    const o = oursRate(ours, rate);
    rows.push({ rate, ladder: l, ours: o, better: judge(l, o, isRevertedStat(CAREER_STAT[rate])) });
  }
  return rows;
};

/** Heroes played on both sides — a game of the ladder's competitive season and a map of ours — most played on our side first. */
export const sharedHeroes = (queue: CareerQueue, ours: CharacterWithUserStats[]) => {
  const bySlug = new Map(ours.filter((hero) => hero.games > 0).map((hero) => [hero.character.slug, hero]));
  return queue.characters
    .flatMap((ladder) => {
      const ourHero = (ladder.games_played ?? 0) > 0 ? bySlug.get(ladder.character) : undefined;
      return ourHero ? [{ ladder, ours: ourHero }] : [];
    })
    .sort((a, b) => b.ours.games - a.ours.games);
};
