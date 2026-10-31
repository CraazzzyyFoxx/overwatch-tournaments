import { describe, expect, it } from "vitest";
import { LogStatsName } from "../stat-names";
import type { StatFormatter } from "@/lib/stats/format";
import { formatStat, resolveMatchMvpPlacement } from "./stats";

const playerWith = (stats: Partial<Record<LogStatsName, number>>) => ({
  stats: { 0: stats as Record<string, number> }
});

/**
 * Stands in for `useFormatter()` / `getFormatter()`. The locale is explicit here
 * because the point of the injected formatter is that `formatStat` no longer
 * picks one: whatever the caller's locale is, is what gets rendered.
 */
const formatterFor = (locale: string): StatFormatter => ({
  number: (value, options) => new Intl.NumberFormat(locale, options).format(value)
});

describe("resolveMatchMvpPlacement", () => {
  it("reads impact_rank", () => {
    const player = playerWith({ [LogStatsName.ImpactRank]: 2 });
    expect(resolveMatchMvpPlacement(player, 0)).toBe(2);
  });

  it("returns null when impact_rank is absent (unscored player)", () => {
    const player = playerWith({});
    expect(resolveMatchMvpPlacement(player, 0)).toBeNull();
  });

  it("returns null for a round the player has no stats row for", () => {
    const player = playerWith({ [LogStatsName.ImpactRank]: 1 });
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
    const recorder: StatFormatter = {
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
    const never: StatFormatter = {
      number: () => {
        throw new Error("formatter must not be used for percent/duration stats");
      }
    };

    expect(formatStat(LogStatsName.WeaponAccuracy, 0.4567, never)).toBe("45.7%");
    expect(formatStat(LogStatsName.WeaponAccuracy, 1.5, never)).toBe("—");
    expect(formatStat(LogStatsName.HeroTimePlayed, 125, never)).toBe("2m 5s");
  });

  it("returns an em dash for absent values", () => {
    const never: StatFormatter = {
      number: () => {
        throw new Error("formatter must not be used for absent values");
      }
    };

    expect(formatStat(LogStatsName.Eliminations, null, never)).toBe("—");
    expect(formatStat(LogStatsName.Eliminations, undefined, never)).toBe("—");
    expect(formatStat(LogStatsName.Eliminations, Number.NaN, never)).toBe("—");
  });
});
