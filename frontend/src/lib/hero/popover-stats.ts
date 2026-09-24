import type { HeroStat } from "@/types/hero.types";
import { LogStatsName } from "@/types/stats.types";

/** The three stats `HeroUserStatsPopover` renders — nothing else is read. */
const POPOVER_STATS: readonly LogStatsName[] = [
  LogStatsName.Winrate,
  LogStatsName.KDA,
  LogStatsName.HeroDamageDealt
];

export type HeroPopoverStat = Pick<HeroStat, "name" | "avg_10">;

/**
 * Narrows a per-hero stats array to what the popover actually shows.
 *
 * The full array carries `best`/`best_all` records (tournament names, map
 * image paths, player names) for every stat, and the profile overview renders
 * one popover per hero row — server-side that whole payload lands in the RSC
 * stream (~139 KB of a 496 KB payload for 7 rows). Keep the two fields the
 * popover reads and drop the rest.
 *
 * Lives outside any `"use client"` module so server components can call it.
 */
export const heroPopoverStats = (stats: HeroStat[] | undefined): HeroPopoverStat[] | undefined =>
  stats
    ?.filter((stat) => POPOVER_STATS.includes(stat.name))
    .map(({ name, avg_10 }) => ({ name, avg_10 }));
