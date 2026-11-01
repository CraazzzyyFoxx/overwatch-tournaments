"use client";

import { useState, type ReactNode } from "react";
import Image from "@/components/ui/image";
import Link from "next/link";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Check, Copy, Download, ExternalLink } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Eyebrow } from "@/components/ui/eyebrow";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { RawLogStatus, matchLogDownloadUrl } from "@/components/match/MatchLogIndicator";
import MatchStatistics from "@/components/match/MatchStatistics";
import { TeamLogo } from "@/components/TeamName";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import encounterService from "@/services/encounter.service";
import { encounterSeatScore, formatSeriesClock } from "@/lib/encounter/detail";
import { duelSeats, duelWinner, seatTeam, type Duel, type DuelSlot } from "@/lib/encounter/seats";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import type { EncounterGameWithMap, Match } from "@/types/encounter.types";

/** What one map of the series already knows: enough to draw the dialog's chrome before its statistics land. */
export interface MatchStatsSeriesEntry {
  /** 1-based position in the series. */
  index: number;
  matchId: number;
  summary: Match;
  game: EncounterGameWithMap | null;
  /** The parsed log's score, in seat order. */
  score: Duel<number> | null;
}

/** Slot 1 teal, slot 2 rose: the page's seat contrast. */
const SEAT_BAR = {
  1: "bg-[color:var(--aqt-teal)]",
  2: "bg-[color:var(--aqt-rose)]"
} as const;
const FACT = "inline-flex min-w-0 items-center gap-1.5";
const FACT_VALUE = "font-medium text-[color:var(--aqt-fg-muted)]";

function digitTone(slot: DuelSlot, winner: DuelSlot | null, loser: string) {
  return winner === slot ? "text-[color:var(--aqt-teal)]" : loser;
}

function Side({
  slot,
  name,
  logo,
  won
}: Readonly<{ slot: DuelSlot; name: string; logo: ReactNode; won: boolean }>) {
  const bar = <span aria-hidden className={cn("h-5 w-0.75 shrink-0 rounded-xs", SEAT_BAR[slot])} />;
  const label = (
    <span
      title={name}
      className={cn(
        "truncate text-ui max-sm:line-clamp-2 max-sm:whitespace-normal max-sm:text-caption",
        won ? "font-semibold text-[color:var(--aqt-fg)]" : "font-medium text-[color:var(--aqt-fg-muted)]"
      )}
    >
      {name}
    </span>
  );
  return slot === 1 ? (
    <div className="flex min-w-0 items-center justify-end gap-2.5 text-end">
      {bar}
      {label}
      {logo}
    </div>
  ) : (
    <div className="flex min-w-0 items-center gap-2.5">
      {logo}
      {label}
      {bar}
    </div>
  );
}

function SeriesSwitcher({
  series,
  currentId,
  onSelect
}: Readonly<{ series: MatchStatsSeriesEntry[]; currentId: number; onSelect: (matchId: number) => void }>) {
  const t = useTranslations();
  return (
    <nav
      aria-label={t("encounters.match.maps")}
      className="flex shrink-0 items-center gap-1.5 overflow-x-auto border-b border-[color:var(--aqt-border)] px-6 py-2.5 max-sm:px-3"
    >
      <Eyebrow className="me-1.5 shrink-0 max-sm:hidden">{t("encounters.match.maps")}</Eyebrow>
      {series.map((entry) => {
        const current = entry.matchId === currentId;
        const map = entry.summary.map ?? entry.game?.map ?? null;
        const mapName = map?.name ?? t("encounters.match.mapAlt");
        const winner = entry.score ? duelWinner(entry.score) : null;
        return (
          <Button
            key={entry.matchId}
            variant={current ? "accent" : "ghost"}
            aria-current={current ? "true" : undefined}
            aria-label={t("encounters.match.mapOption", {
              index: entry.index,
              map: mapName,
              score: entry.score ? `${entry.score.one}:${entry.score.two}` : t("encounters.detail.mapNotPlayed")
            })}
            onClick={() => onSelect(entry.matchId)}
            className={cn(
              "h-10 shrink-0 gap-2 ps-1 pe-2.5 max-sm:ps-2.5",
              !current && "text-[color:var(--aqt-fg-muted)]"
            )}
          >
            {map?.image_path ? (
              <Image
                src={map.image_path}
                alt=""
                aria-hidden
                width={44}
                height={30}
                className="h-7.5 w-11 rounded-sm object-cover max-sm:hidden"
              />
            ) : null}
            <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">{entry.index}</span>
            <span className="text-caption font-medium">{mapName}</span>
            {entry.score ? (
              <span className="aqt-tnum ms-1 flex items-baseline gap-1 border-s border-[color:var(--aqt-border-2)] ps-3 text-caption font-semibold">
                <span className={digitTone(1, winner, "text-[color:var(--aqt-fg-faint)]")}>{entry.score.one}</span>
                <span aria-hidden className="text-[color:var(--aqt-fg-faint)]">
                  :
                </span>
                <span className={digitTone(2, winner, "text-[color:var(--aqt-fg-faint)]")}>{entry.score.two}</span>
              </span>
            ) : null}
          </Button>
        );
      })}
    </nav>
  );
}

function CopyReplay({ code }: Readonly<{ code: string }>) {
  const t = useTranslations();
  const [copied, setCopied] = useState(false);
  return (
    <>
      <Button
        variant="ghost"
        size="icon-sm"
        className="size-6"
        aria-label={t("encounters.match.copyReplay")}
        onClick={() => {
          void navigator.clipboard.writeText(code).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          });
        }}
      >
        {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      </Button>
      <span className="sr-only" aria-live="polite">
        {copied ? t("encounters.match.copied") : ""}
      </span>
    </>
  );
}

/**
 * One parsed match's scoreboard: header and `MatchStatistics`, read by match id
 * once the dialog opens (the key is the one the series-statistics panel uses,
 * so whichever loads first warms the other).
 *
 * A tournament map hands over what its row already knows (`summary`, `names`,
 * `score`, `game`) so the header is complete before the read lands; without
 * them (a mix's history row) the header is drawn from the loaded match alone.
 * `series` (every played map of the encounter, in order) adds a switcher that
 * shows another map's statistics in the same dialog; the dialog opens on
 * `matchId` and returns to it when closed. `showMatchLink={false}` drops the
 * `/matches/{id}` page link for matches that live only inside their mix.
 */
export default function MatchStatsDialog({
  matchId,
  trigger,
  summary,
  names,
  score,
  game,
  series,
  showMatchLink = true
}: Readonly<{
  matchId: number;
  trigger: ReactNode;
  summary?: Match | null;
  names?: Duel<string>;
  score?: Duel<number> | null;
  game?: EncounterGameWithMap | null;
  series?: MatchStatsSeriesEntry[];
  showMatchLink?: boolean;
}>) {
  const t = useTranslations();
  const { status: authStatus } = useAuthProfile();
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<number | null>(null);
  const currentId = picked ?? matchId;
  const entry = series?.find((item) => item.matchId === currentId) ?? null;
  const own = entry ?? { summary, game, score };
  const matchQuery = useQuery({
    queryKey: encounterQueryKeys.matchDetail(currentId),
    queryFn: () => encounterService.getMatch(currentId),
    enabled: open,
    staleTime: 5 * 60_000,
    // Switching maps keeps the open tab and round: the previous map's statistics stay mounted (dimmed) until
    // the next one lands, instead of a skeleton that would reset them.
    placeholderData: keepPreviousData
  });
  const switching = matchQuery.isPlaceholderData;
  // The header always describes the picked map, never the placeholder still in the body.
  const match: Match | null = (switching ? null : matchQuery.data) ?? own.summary ?? null;
  const currentGame = own.game ?? null;
  const [seatOne, seatTwo] = duelSeats(match?.encounter?.teams);
  const shownNames = names ?? { one: seatOne?.name ?? t("common.tbd"), two: seatTwo?.name ?? t("common.tbd") };
  const shownScore =
    own.score !== undefined ? own.score : match?.encounter ? encounterSeatScore(match, match.encounter) : null;
  const winner = shownScore ? duelWinner(shownScore) : null;
  const map = match?.map ?? currentGame?.map ?? null;
  const mapName = map?.name ?? t("encounters.match.mapAlt");
  // The match's own mode: a map several modes share (Deadlock's Midtown) has no parent to name it.
  const mode = match?.mode ?? currentGame?.mode ?? map?.parent ?? null;
  const duration =
    match != null
      ? formatSeriesClock(match.duration_s, { h: t("common.duration.h"), m: t("common.duration.m"), s: t("common.duration.s") })
      : null;
  const replayCode = currentGame?.teams.find((line) => line.replay_code)?.replay_code ?? null;
  const logDownloadable = match?.raw_available === true && authStatus === "authenticated";
  const logo = (seat: typeof seatOne) => <TeamLogo team={seatTeam(seat)} size="md" className="max-sm:hidden" />;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setPicked(null);
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent
        variant="panel"
        aria-describedby={undefined}
        className="w-[calc(100%-2rem)] max-w-[1180px] max-sm:inset-0 max-sm:h-dvh max-sm:max-h-dvh max-sm:w-full max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none max-sm:border-0"
      >
        <DialogHeader
          variant="panel"
          className="relative isolate space-y-0 py-4.5 ps-6 pe-12 max-sm:py-3.5 max-sm:ps-3"
        >
          {map?.image_path ? (
            <div
              aria-hidden
              className="absolute inset-0 -z-10 opacity-20 [mask-image:linear-gradient(90deg,transparent_0%,var(--aqt-bg)_45%,var(--aqt-bg)_70%,transparent_100%)]"
            >
              <Image
                src={map.image_path}
                alt=""
                fill
                sizes="(min-width: 1180px) 1180px, 100vw"
                className="object-cover object-[50%_40%]"
              />
            </div>
          ) : null}
          <div className="flex items-center gap-2.5">
            {mode?.image_path ? (
              <Image src={mode.image_path} alt="" width={22} height={22} aria-hidden className="shrink-0" />
            ) : null}
            <DialogTitle className="font-display text-title font-semibold max-sm:text-heading">{mapName}</DialogTitle>
            <span className="text-body text-[color:var(--aqt-fg-dim)] max-sm:hidden">
              {mode ? `· ${mode.name}` : null}
              {duration ? (
                <>
                  {" · "}
                  <span className="aqt-tnum">{duration}</span>
                </>
              ) : null}
            </span>
          </div>
          <div
            role="group"
            aria-label={
              shownScore
                ? t("encounters.detail.mapScoreAria", {
                    first: shownNames.one,
                    second: shownNames.two,
                    firstScore: shownScore.one,
                    secondScore: shownScore.two
                  })
                : undefined
            }
            className="mt-4 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-8 pb-0.5 max-sm:mt-3 max-sm:gap-3"
          >
            <Side slot={1} name={shownNames.one} won={winner === 1} logo={logo(seatOne)} />
            <div
              aria-hidden
              className="aqt-tnum flex items-baseline gap-4 px-2 font-display text-headline font-bold max-sm:gap-2.5 max-sm:px-0"
            >
              {shownScore ? (
                <>
                  <span className={cn("min-w-[.8em] text-center", digitTone(1, winner, "text-[color:var(--aqt-fg-muted)]"))}>
                    {shownScore.one}
                  </span>
                  <span className="-translate-y-1 text-heading text-[color:var(--aqt-fg-faint)]">:</span>
                  <span className={cn("min-w-[.8em] text-center", digitTone(2, winner, "text-[color:var(--aqt-fg-muted)]"))}>
                    {shownScore.two}
                  </span>
                </>
              ) : (
                <span className="text-[color:var(--aqt-fg-faint)]">—</span>
              )}
            </div>
            <Side slot={2} name={shownNames.two} won={winner === 2} logo={logo(seatTwo)} />
          </div>
          {winner ? (
            <span className="sr-only">
              {t("encounters.match.wonBy", { team: winner === 1 ? shownNames.one : shownNames.two })}
            </span>
          ) : null}
        </DialogHeader>

        {series && series.length >= 2 ? (
          <SeriesSwitcher series={series} currentId={currentId} onSelect={setPicked} />
        ) : null}

        <div
          className="min-h-0 flex-1 overflow-y-auto px-6 py-4 max-sm:px-3"
          aria-busy={switching || undefined}
        >
          {matchQuery.isError ? (
            <PageStateCard state="error" onAction={() => void matchQuery.refetch()} />
          ) : matchQuery.data ? (
            <div className={cn("transition-opacity", switching && "pointer-events-none opacity-50")}>
              <MatchStatistics match={matchQuery.data} />
            </div>
          ) : (
            <div className="flex flex-col gap-2" aria-busy>
              {Array.from({ length: 8 }).map((_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
              ))}
            </div>
          )}
        </div>

        {match != null ? (
          <DialogFooter
            variant="panel"
            className="flex-row flex-wrap items-center justify-between gap-x-4 gap-y-2 px-6 py-2.5 max-sm:px-3 sm:justify-between"
          >
            <div className="flex min-w-0 flex-wrap items-center gap-x-3.5 gap-y-1 text-caption text-[color:var(--aqt-fg-dim)]">
              {currentGame?.result_source != null ? (
                <span className={FACT}>
                  {t("encounters.match.source")}
                  <span className={FACT_VALUE}>
                    {t(`encounters.game.source.${currentGame.result_source}` as never)}
                  </span>
                </span>
              ) : null}
              {replayCode ? (
                <span className={FACT}>
                  {t("encounters.match.replayCode")}
                  <span className={cn(FACT_VALUE, "aqt-tnum")}>{replayCode}</span>
                  <CopyReplay code={replayCode} />
                </span>
              ) : null}
              {match.log_name ? (
                <span className={cn(FACT, "max-sm:hidden")}>
                  {t("encounters.match.logName")}
                  <span title={match.log_name} className={cn(FACT_VALUE, "max-w-64 truncate")}>
                    {match.log_name}
                  </span>
                  <RawLogStatus raw_status={match.raw_status} raw_available={match.raw_available} variant="icon" />
                </span>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {logDownloadable ? (
                <Button variant="outline" size="sm" asChild>
                  <a href={matchLogDownloadUrl(match.id)} download>
                    <Download aria-hidden />
                    {t("encounters.match.downloadLog")}
                  </a>
                </Button>
              ) : null}
              {showMatchLink ? (
                <Button variant="outline" size="sm" asChild>
                  <Link href={`/matches/${match.id}`} target="_blank" rel="noopener noreferrer">
                    <ExternalLink aria-hidden />
                    {t("encounters.match.matchPage")}
                  </Link>
                </Button>
              ) : null}
            </div>
          </DialogFooter>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
