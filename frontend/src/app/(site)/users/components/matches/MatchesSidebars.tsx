"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { CardSurface, StagePill } from "@/app/(site)/users/components/shared/atoms";
import { ArrowLeftRight, ListOrdered } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";

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

// Top N shown inline; the rest live behind the "All N →" head-to-head modal.
const SIDEBAR_LIMIT = 8;

const oppTotal = (o: OpponentStat) => o.wins + o.losses + o.draws;
const oppWinrate = (o: OpponentStat) => {
  const total = oppTotal(o);
  return total > 0 ? (o.wins / total) * 100 : 0;
};
const wrColor = (wr: number, total: number) =>
  total === 0 ? "var(--aqt-fg-faint)" : wr > 55 ? "var(--aqt-emerald)" : wr < 45 ? "var(--aqt-rose)" : "var(--aqt-amber)";

const OpponentPips = ({ o }: { o: OpponentStat }) => (
  <span className="aqt-wl">
    {Array.from({ length: o.wins }).map((_, idx) => <span key={`w${idx}`} className="b w" />)}
    {Array.from({ length: o.losses }).map((_, idx) => <span key={`l${idx}`} className="b l" />)}
    {Array.from({ length: o.draws }).map((_, idx) => <span key={`d${idx}`} className="b d" />)}
  </span>
);

const OpponentRecord = ({ o }: { o: OpponentStat }) => (
  <>
    <b className="text-[color:var(--aqt-emerald)]">{o.wins}</b>
    <span className="text-[color:var(--aqt-fg-faint)]">–{o.draws}</span>
    <span className="text-[color:var(--aqt-rose)]">–{o.losses}</span>
  </>
);

const thLeft =
  "aqt-mono border-b border-[color:var(--aqt-border)] px-3 py-2 text-left text-[10.5px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]";
const thRight = `${thLeft} text-right`;

const MatchesSidebars = ({ opponentStats, stageStats }: MatchesSidebarsProps) => {
  const t = useTranslations();
  const stageLabels: Record<"group" | "playoffs" | "finals", string> = {
    group: t("users.matches.filters.group"),
    playoffs: t("users.matches.filters.playoffs"),
    finals: t("users.matches.filters.finals")
  };
  const shown = opponentStats.slice(0, SIDEBAR_LIMIT);

  return (
    <aside className="flex flex-col gap-3.5 xl:sticky xl:top-22">
      <CardSurface
        flush
        title={t("users.matches.mostFoughtOpponents")}
        icon={<ArrowLeftRight size={15} />}
        action={
          opponentStats.length > SIDEBAR_LIMIT ? (
            <Dialog>
              <DialogTrigger className="aqt-seeall">
                {t("common.all")} {opponentStats.length} →
              </DialogTrigger>
              <DialogContent className="max-w-[560px] border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]">
                <DialogHeader>
                  <DialogTitle className="font-onest text-[color:var(--aqt-fg)]">
                    {t("users.matches.allOpponents")}
                  </DialogTitle>
                </DialogHeader>
                <div className="max-h-[60vh] overflow-y-auto">
                  <table className="w-full border-collapse text-[13px]">
                    <thead>
                      <tr>
                        <th className={thLeft} style={{ width: 34 }}>#</th>
                        <th className={thLeft}>{t("users.matches.colOpponent")}</th>
                        <th className={thRight}>{t("standings.colWDL")}</th>
                        <th className={thRight}>{t("users.matches.colWinrate")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {opponentStats.map((o, i) => {
                        const total = oppTotal(o);
                        const wr = oppWinrate(o);
                        return (
                          <tr
                            key={o.name}
                            className="border-b border-[color:var(--aqt-border)] last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]"
                          >
                            <td className="aqt-mono px-3 py-2 text-[color:var(--aqt-fg-faint)]">
                              {String(i + 1).padStart(2, "0")}
                            </td>
                            <td className="px-3 py-2 font-semibold text-[color:var(--aqt-fg)]">{o.name}</td>
                            <td className="aqt-mono px-3 py-2 text-right">
                              <OpponentRecord o={o} />
                            </td>
                            <td
                              className="aqt-mono px-3 py-2 text-right font-bold"
                              style={{ color: wrColor(wr, total) }}
                            >
                              {total > 0 ? `${wr.toFixed(0)}%` : "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </DialogContent>
            </Dialog>
          ) : undefined
        }
      >
        {shown.map((opp, i) => (
          <div key={opp.name} className="aqt-opp-row">
            <span className="aqt-rank">{String(i + 1).padStart(2, "0")}</span>
            <span className="aqt-nm">{opp.name}</span>
            <OpponentPips o={opp} />
            <span className="aqt-pct">
              {opp.wins}-{opp.losses}{opp.draws > 0 ? `-${opp.draws}` : ""}
            </span>
          </div>
        ))}
        {opponentStats.length === 0 ? (
          <div className="p-4 text-center text-[13px] text-[color:var(--aqt-fg-dim)]">{t("users.matches.noData")}</div>
        ) : null}
      </CardSurface>

      <CardSurface flush title={t("users.matches.byStage")} icon={<ListOrdered size={15} />}>
        {(["group", "playoffs", "finals"] as const).map((k) => {
          const stats = stageStats[k];
          const total = stats.w + stats.l;
          const winrate = total > 0 ? (stats.w / total) * 100 : 0;
          return (
            <div key={k} className="aqt-opp-row" style={{ gridTemplateColumns: "1fr auto auto" }}>
              <span className="aqt-nm inline-flex items-center gap-2">
                <StagePill kind={k}>{stageLabels[k]}</StagePill>
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
