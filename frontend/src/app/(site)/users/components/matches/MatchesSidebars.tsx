"use client";

import { useTranslations } from "next-intl";
import { CardSurface } from "@/components/profile/atoms";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { winrateColor } from "@/lib/colors";
import { cn } from "@/lib/utils";
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

const PIP = "h-4.5 w-1.5 rounded-xs";

const OpponentPips = ({ o }: { o: OpponentStat }) => (
  <span className="inline-flex gap-0.5" aria-hidden>
    {Array.from({ length: o.wins }).map((_, idx) => <span key={`w${idx}`} className={cn(PIP, "bg-[color:var(--aqt-emerald)]")} />)}
    {Array.from({ length: o.losses }).map((_, idx) => <span key={`l${idx}`} className={cn(PIP, "bg-[color:var(--aqt-rose)]")} />)}
    {Array.from({ length: o.draws }).map((_, idx) => <span key={`d${idx}`} className={cn(PIP, "bg-[color:var(--aqt-amber)]")} />)}
  </span>
);

const ROW =
  "grid grid-cols-[1fr_auto_auto] items-center gap-2.5 border-b border-[color:var(--aqt-border)] px-3.5 py-2.25 text-caption last:border-b-0";
const ROW_NAME = "font-semibold text-[color:var(--aqt-fg)]";
const ROW_RECORD = "aqt-tnum min-w-8.5 text-right text-label font-semibold text-[color:var(--aqt-fg-muted)]";

const OpponentRecord = ({ o }: { o: OpponentStat }) => (
  <>
    <b className="text-[color:var(--aqt-emerald)]">{o.wins}</b>
    <span className="text-[color:var(--aqt-fg-faint)]">–{o.draws}</span>
    <span className="text-[color:var(--aqt-rose)]">–{o.losses}</span>
  </>
);

const thLeft = "aqt-tnum px-3 py-2";
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
              <DialogTrigger asChild>
                <Button variant="link" size="inline" className="[&_svg]:size-3" aria-label={t("users.matches.allOpponents")}>
                  <span className="tabular-nums">
                    {t("common.all")} {opponentStats.length}
                  </span>
                  <ArrowRight aria-hidden />
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-[560px]">
                <DialogHeader>
                  <DialogTitle>{t("users.matches.allOpponents")}</DialogTitle>
                </DialogHeader>
                <Table wrapperClassName="max-h-[60vh] overflow-y-auto" className="border-collapse">
                  <TableHeader>
                    <TableRow>
                      <TableHead className={thLeft}>{t("users.matches.colOpponent")}</TableHead>
                      <TableHead className={thRight}>{t("standings.colWDL")}</TableHead>
                      <TableHead className={thRight}>{t("users.matches.colWinrate")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {opponentStats.map((o) => {
                      const total = oppTotal(o);
                      const wr = oppWinrate(o);
                      return (
                        <TableRow key={o.name}>
                          <TableCell className="px-3 py-2 font-semibold text-[color:var(--aqt-fg)]">{o.name}</TableCell>
                          <TableCell className="aqt-tnum px-3 py-2 text-right">
                            <OpponentRecord o={o} />
                          </TableCell>
                          <TableCell
                            className="aqt-tnum px-3 py-2 text-right font-bold"
                            style={{ color: total > 0 ? winrateColor(wr) : "var(--aqt-fg-faint)" }}
                          >
                            {total > 0 ? `${wr.toFixed(0)}%` : "—"}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </DialogContent>
            </Dialog>
          ) : undefined
        }
      >
        {shown.map((opp) => (
          <div key={opp.name} className={ROW}>
            <span className={ROW_NAME}>{opp.name}</span>
            <OpponentPips o={opp} />
            <span className={ROW_RECORD}>
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
            <div key={k} className={ROW}>
              <span className={ROW_NAME}>{stageLabels[k]}</span>
              <span className={ROW_RECORD}>{stats.w}-{stats.l}</span>
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
