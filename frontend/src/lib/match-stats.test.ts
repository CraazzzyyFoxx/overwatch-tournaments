import { describe, expect, it } from "vitest";
import { LogStatsName } from "@/types/stats.types";
import { formatStat, resolveMatchMvpPlacement, type StatNumberFormatter } from "@/lib/match-stats";
import type { PlayerWithStats } from "@/types/team.types";

const playerWith = (stats: Partial<Record<LogStatsName, number>>): PlayerWithStats =>
  ({
    stats: { 0: stats as Record<LogStatsName, number> },
    heroes: {}
  }) as PlayerWithStats;

/**
 * Stands in for `useFormatter()` / `getFormatter()`. The locale is explicit here
 * because the point of the injected formatter is that `formatStat` no longer
 * picks one: whatever the caller's locale is, is what gets rendered.
 */
const formatterFor = (locale: string): StatNumberFormatter => ({
  number: (value, options) => new Intl.NumberFormat(locale, options).format(value)
});

describe("resolveMatchMvpPlacement", () => {
  it("prefers impact_rank over legacy performance", () => {
    const player = playerWith({ [LogStatsName.ImpactRank]: 2, [LogStatsName.Performance]: 1 });
    expect(resolveMatchMvpPlacement(player, 0)).toBe(2);
  });

  it("falls back to performance when impact_rank is absent (legacy match)", () => {
    const player = playerWith({ [LogStatsName.Performance]: 3 });
    expect(resolveMatchMvpPlacement(player, 0)).toBe(3);
  });

  it("returns null when neither stat exists for the round", () => {
    const player = playerWith({});
    expect(resolveMatchMvpPlacement(player, 0)).toBeNull();
  });

  it("returns null for a round the player has no stats row for", () => {
    const player = playerWith({ [LogStatsName.Performance]: 1 });
    expect(resolveMatchMvpPlacement(player, 1)).toBeNull();
  });
});

describe("formatStat", () => {
  it("renders thousands through the caller's formatter", () => {
    // The grouping the old module-level formatter produced back when it pinned
    // en-US — still reachable, but now only because the caller asked for it.
    expect(formatStat(LogStatsName.HeroDamageDealt, 1557, formatterFor("en-US"))).toBe("1,557");
  });

  it("follows the supplied locale instead of pinning one", () => {
    // ru is the app's default locale, and it does not group with commas. The
    // exact separator glyph is ICU's business; that the two disagree is ours.
    const ru = formatStat(LogStatsName.HeroDamageDealt, 1557, formatterFor("ru-RU"));
    expect(ru).not.toBe("1,557");
    expect(ru).not.toContain(",");
  });

  it("delegates every numeric render to the formatter", () => {
    const seen: number[] = [];
    const recorder: StatNumberFormatter = {
      number: (value) => {
        seen.push(value);
        return String(value);
      }
    };

    expect(formatStat(LogStatsName.Eliminations, 12.4, recorder)).toBe("12");
    expect(formatStat(LogStatsName.KD, 2.25, recorder)).toBe("2.25");
    expect(seen).toEqual([12, 2.25]);
  });

  it("formats percent and duration without the formatter", () => {
    const never: StatNumberFormatter = {
      number: () => {
        throw new Error("formatter must not be used for percent/duration stats");
      }
    };

    expect(formatStat(LogStatsName.WeaponAccuracy, 0.4567, never)).toBe("45.7%");
    expect(formatStat(LogStatsName.WeaponAccuracy, 1.5, never)).toBe("—");
    expect(formatStat(LogStatsName.HeroTimePlayed, 125, never)).toBe("2m 5s");
  });

  it("returns an em dash for absent values", () => {
    const never: StatNumberFormatter = {
      number: () => {
        throw new Error("formatter must not be used for absent values");
      }
    };

    expect(formatStat(LogStatsName.Eliminations, null, never)).toBe("—");
    expect(formatStat(LogStatsName.Eliminations, undefined, never)).toBe("—");
    expect(formatStat(LogStatsName.Eliminations, Number.NaN, never)).toBe("—");
  });
});
