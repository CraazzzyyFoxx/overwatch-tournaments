"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { TeamWithStats } from "@/types/team.types";
import { LogStatsName } from "@/types/stats.types";
import { COMPARISON_STATS, STAT_META, formatStat, teamTotal } from "@/utils/matchStats";

interface MatchTeamComparisonProps {
  home: TeamWithStats;
  away: TeamWithStats;
  round: number;
}

interface Row {
  name: LogStatsName;
  label: string;
  home: number;
  away: number;
  homePct: number;
  awayPct: number;
  /** Side that "wins" the stat (respecting lower-is-better stats). */
  winner: "home" | "away" | "tie";
}

const MatchTeamComparison = ({ home, away, round }: MatchTeamComparisonProps) => {
  const t = useTranslations<never>();

  const rows: Row[] = COMPARISON_STATS.map((name) => {
    const homeValue = teamTotal(home, round, name);
    const awayValue = teamTotal(away, round, name);
    const total = homeValue + awayValue;
    const reverted = Boolean(STAT_META[name]?.reverted);
    let winner: Row["winner"] = "tie";
    if (homeValue !== awayValue) {
      const homeBetter = reverted ? homeValue < awayValue : homeValue > awayValue;
      winner = homeBetter ? "home" : "away";
    }
    return {
      name,
      label: t((STAT_META[name]?.labelKey ?? name) as Parameters<typeof t>[0]),
      home: homeValue,
      away: awayValue,
      // Clamp to [0,100]: guards against signed stats (e.g. DamageDelta) that a
      // future edit could add to COMPARISON_STATS producing >100% / negative widths.
      homePct: total > 0 ? Math.max(0, Math.min(100, (homeValue / total) * 100)) : 0,
      awayPct: total > 0 ? Math.max(0, Math.min(100, (awayValue / total) * 100)) : 0,
      winner
    };
  });

  return (
    <div className="rounded-[12px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]">
      <div className="flex items-center justify-between border-b border-[color:var(--aqt-border)] px-4 py-3">
        <span className="aqt-tnum truncate text-sm font-semibold text-[color:var(--aqt-teal)]">{home.name}</span>
        <span className="aqt-mono px-2 text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
          {t("matches.comparison.title")}
        </span>
        <span className="aqt-tnum truncate text-right text-sm font-semibold text-[color:var(--aqt-rose)]">
          {away.name}
        </span>
      </div>
      <div className="flex flex-col gap-2.5 px-4 py-4">
        {rows.map((row) => (
          <div key={row.name} className="grid grid-cols-[minmax(56px,auto)_1fr_minmax(56px,auto)] items-center gap-3">
            <span
              className="aqt-tnum text-right text-[13px]"
              style={{
                color: row.winner === "home" ? "var(--aqt-teal)" : "var(--aqt-fg-muted)",
                fontWeight: row.winner === "home" ? 700 : 500
              }}
            >
              {formatStat(row.name, row.home)}
            </span>
            <div className="flex flex-col gap-1">
              <span className="text-center text-[10px] font-semibold uppercase tracking-[0.08em] text-[color:var(--aqt-fg-dim)]">
                {row.label}
              </span>
              <div className="flex items-center">
                <div className="flex flex-1 justify-end">
                  <div
                    className="h-[6px] rounded-l-full"
                    style={{
                      width: `${row.homePct}%`,
                      background: "var(--aqt-teal)",
                      opacity: row.winner === "away" ? 0.4 : 0.9
                    }}
                  />
                </div>
                <div className="h-[10px] w-px bg-[color:var(--aqt-border-2)]" />
                <div className="flex flex-1 justify-start">
                  <div
                    className="h-[6px] rounded-r-full"
                    style={{
                      width: `${row.awayPct}%`,
                      background: "var(--aqt-rose)",
                      opacity: row.winner === "home" ? 0.4 : 0.9
                    }}
                  />
                </div>
              </div>
            </div>
            <span
              className="aqt-tnum text-left text-[13px]"
              style={{
                color: row.winner === "away" ? "var(--aqt-rose)" : "var(--aqt-fg-muted)",
                fontWeight: row.winner === "away" ? 700 : 500
              }}
            >
              {formatStat(row.name, row.away)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default MatchTeamComparison;
