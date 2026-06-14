"use client";

import React from "react";
import { CardSurface, StagePill } from "@/app/(site)/users/components/shared/atoms";
import { ArrowLeftRight, ListOrdered } from "lucide-react";

export interface OpponentStat {
  name: string;
  wins: number;
  losses: number;
  draws: number;
}

export interface StageStats {
  group: { w: number; l: number };
  playoffs: { w: number; l: number };
  finals: { w: number; l: number };
}

interface MatchesSidebarsProps {
  opponentStats: OpponentStat[];
  stageStats: StageStats;
}

const MatchesSidebars = ({ opponentStats, stageStats }: MatchesSidebarsProps) => {
  return (
    <aside className="flex flex-col gap-3.5 xl:sticky xl:top-22">
      <CardSurface flush title="Most-fought opponents" icon={<ArrowLeftRight size={15} />}>
        {opponentStats.map((opp, i) => (
          <div key={opp.name} className="aqt-opp-row">
            <span className="aqt-rank">{String(i + 1).padStart(2, "0")}</span>
            <span className="aqt-nm">{opp.name}</span>
            <span className="aqt-wl">
              {Array.from({ length: opp.wins }).map((_, idx) => <span key={`w${idx}`} className="b w" />)}
              {Array.from({ length: opp.losses }).map((_, idx) => <span key={`l${idx}`} className="b l" />)}
              {Array.from({ length: opp.draws }).map((_, idx) => <span key={`d${idx}`} className="b d" />)}
            </span>
            <span className="aqt-pct">
              {opp.wins}-{opp.losses}{opp.draws > 0 ? `-${opp.draws}` : ""}
            </span>
          </div>
        ))}
        {opponentStats.length === 0 ? (
          <div className="p-4 text-center text-[13px] text-[color:var(--aqt-fg-dim)]">No data</div>
        ) : null}
      </CardSurface>

      <CardSurface flush title="By stage" icon={<ListOrdered size={15} />}>
        {(["group", "playoffs", "finals"] as const).map((k) => {
          const stats = stageStats[k];
          const total = stats.w + stats.l;
          const winrate = total > 0 ? (stats.w / total) * 100 : 0;
          return (
            <div key={k} className="aqt-opp-row" style={{ gridTemplateColumns: "1fr auto auto" }}>
              <span className="aqt-nm inline-flex items-center gap-2">
                <StagePill kind={k}>{k.charAt(0).toUpperCase() + k.slice(1)}</StagePill>
              </span>
              <span className="aqt-pct">{stats.w}-{stats.l}</span>
              <span
                className="aqt-mono text-[12px] font-bold"
                style={{
                  color: winrate > 55 ? "var(--aqt-emerald)" : winrate < 45 ? "var(--aqt-rose)" : "var(--aqt-amber)"
                }}
              >
                {total > 0 ? `${winrate.toFixed(0)}%` : "—"}
              </span>
            </div>
          );
        })}
      </CardSurface>
    </aside>
  );
};

export default MatchesSidebars;
