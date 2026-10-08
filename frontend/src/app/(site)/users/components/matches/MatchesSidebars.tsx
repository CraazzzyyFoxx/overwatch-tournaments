"use client";

import { useTranslations } from "next-intl";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import { winrateColor } from "@/app/(site)/users/components/heroes/utils";
import { ArrowRight } from "lucide-react";
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

// Top N shown inline; the rest live behind the "All N" head-to-head modal.
const SIDEBAR_LIMIT = 8;

const oppTotal = (o: OpponentStat) => o.wins + o.losses + o.draws;
const oppWinrate = (o: OpponentStat) => {
  const total = oppTotal(o);
  return total > 0 ? (o.wins / total) * 100 : 0;
};

const OpponentPips = ({ o }: { o: OpponentStat }) => (
  <span className="aqt-wl" aria-hidden>
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
  "aqt-tnum border-b border-[color:var(--aqt-border)] px-3 py-2 text-left text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]";
const thRight = `${thLeft} text-right`;

const MatchesSidebars = ({ opponentStats, stageStats }: MatchesSidebarsProps) => {
  const t = useTranslations();
  const stageLabels: Record<"group" | "playoffs" | "finals", string> = {
    group: t("users.matches.filters.group"),
    playoffs: t("users.matches.filters.playoffs"),
    finals: t("users.matches.filters.finals")
  };
  const shown = opponentStats.slice(0, SIDEBAR_LIMIT);

  // Sticky rail: shared offset token, and a stacking context below the z-40 tab
  // strip so it scrolls under the opaque bar instead of through it.
  return (
    <aside className="flex flex-col gap-3.5 xl:sticky xl:top-[var(--aqt-sticky-top)] xl:z-30">
      <CardSurface
        flush
        title={t("users.matches.mostFoughtOpponents")}
        action={
          opponentStats.length > SIDEBAR_LIMIT ? (
            <Dialog>
              <DialogTrigger className="aqt-pf-link" aria-label={t("users.matches.allOpponents")}>
                <span className="tabular-nums">
                  {t("common.all")} {opponentStats.length}
                </span>
                <ArrowRight aria-hidden className="size-3" />
              </DialogTrigger>
              <DialogContent className="max-w-[560px] border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]">
                <DialogHeader>
                  <DialogTitle className="font-onest text-[color:var(--aqt-fg)]">
                    {t("users.matches.allOpponents")}
                  </DialogTitle>
                </DialogHeader>
                <div className="max-h-[60vh] overflow-y-auto">
                  <table className="w-full border-collapse text-caption">
                    <thead>
                      <tr>
                        <th className={thLeft}>{t("users.matches.colOpponent")}</th>
                        <th className={thRight}>{t("standings.colWDL")}</th>
                        <th className={thRight}>{t("users.matches.colWinrate")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {opponentStats.map((o) => {
                        const total = oppTotal(o);
                        const wr = oppWinrate(o);
                        return (
                          <tr
                            key={o.name}
                            className="border-b border-[color:var(--aqt-border)] last:border-b-0 hover:bg-[color:var(--aqt-overlay-2)]"
                          >
                            <td className="px-3 py-2 font-semibold text-[color:var(--aqt-fg)]">{o.name}</td>
                            <td className="aqt-tnum px-3 py-2 text-right">
                              <OpponentRecord o={o} />
                            </td>
                            <td
                              className="aqt-tnum px-3 py-2 text-right font-bold"
                              style={{ color: total > 0 ? winrateColor(wr) : "var(--aqt-fg-faint)" }}
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
        {shown.map((opp) => (
          <div key={opp.name} className="aqt-opp-row">
            <span className="aqt-nm">{opp.name}</span>
            <OpponentPips o={opp} />
            <span className="aqt-pct tabular-nums">
              {opp.wins}-{opp.losses}{opp.draws > 0 ? `-${opp.draws}` : ""}
            </span>
          </div>
        ))}
        {opponentStats.length === 0 ? (
          <div className="p-4 text-center text-caption text-[color:var(--aqt-fg-dim)]">{t("users.matches.noData")}</div>
        ) : null}
      </CardSurface>

      <CardSurface flush title={t("users.matches.byStage")}>
        {(["group", "playoffs", "finals"] as const).map((k) => {
          const stats = stageStats[k];
          const total = stats.w + stats.l;
          const winrate = total > 0 ? (stats.w / total) * 100 : 0;
          return (
            <div key={k} className="aqt-opp-row">
              <span className="aqt-nm">{stageLabels[k]}</span>
              <span className="aqt-pct tabular-nums">{stats.w}-{stats.l}</span>
              <span
                className="aqt-tnum text-label font-bold"
                style={{ color: total > 0 ? winrateColor(winrate) : "var(--aqt-fg-faint)" }}
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
