"use client";

import { useState, type ReactNode } from "react";
import Image from "@/components/ui/image";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ExternalLink } from "lucide-react";

import { cn } from "@/lib/utils";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Eyebrow } from "@/components/ui/eyebrow";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import MatchLogIndicator, { RawLogStatus } from "@/components/match/MatchLogIndicator";
import MatchStatistics from "@/components/match/MatchStatistics";
import { CARD_SUB, SIDE_TEXT } from "@/components/match/EncounterAtoms";
import encounterService from "@/services/encounter.service";
import { encounterSeatScore, formatSeriesClock } from "@/lib/encounter/detail";
import { mapWithModeName } from "@/lib/catalog/mode";
import { duelSeats, type Duel } from "@/lib/encounter/seats";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import type { EncounterGameWithMap, Match } from "@/types/encounter.types";

const SCORE_SEP = "text-label text-[color:var(--aqt-fg-faint)]";
const DIALOG_FACT = "inline-flex min-w-0 items-center gap-1.5";
const DIALOG_FACT_VALUE = "inline-flex min-w-0 items-center gap-1.5 text-[color:var(--aqt-fg-muted)]";
const DIALOG_TEAM = "max-w-44 truncate text-caption font-semibold";

/**
 * One parsed match's scoreboard: header and `MatchStatistics`, read by match id
 * once the dialog opens (the key is the one the series-statistics panel uses,
 * so whichever loads first warms the other).
 *
 * A tournament map hands over what its row already knows (`summary`, `names`,
 * `score`, `game`) so the header is complete before the read lands; without
 * them (a mix's history row) the header is drawn from the loaded match alone.
 * `showMatchLink={false}` drops the `/matches/{id}` page link for matches that
 * live only inside their mix.
 */
export default function MatchStatsDialog({
  matchId,
  trigger,
  summary,
  names,
  score,
  game,
  showMatchLink = true
}: Readonly<{
  matchId: number;
  trigger: ReactNode;
  summary?: Match | null;
  names?: Duel<string>;
  score?: Duel<number> | null;
  game?: EncounterGameWithMap | null;
  showMatchLink?: boolean;
}>) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const matchQuery = useQuery({
    queryKey: encounterQueryKeys.matchDetail(matchId),
    queryFn: () => encounterService.getMatch(matchId),
    enabled: open,
    staleTime: 5 * 60_000
  });
  const match: Match | null = matchQuery.data ?? summary ?? null;

  const [seatOne, seatTwo] = duelSeats(match?.encounter?.teams);
  const shownNames = names ?? { one: seatOne?.name ?? t("common.tbd"), two: seatTwo?.name ?? t("common.tbd") };
  const shownScore = score !== undefined ? score : match?.encounter ? encounterSeatScore(match, match.encounter) : null;
  const map = match?.map ?? game?.map ?? null;
  const mapName = map?.name ?? t("encounters.match.mapAlt");
  // The match's own mode: a map several modes share (Deadlock's Midtown) has no parent to name it.
  const mode = match?.mode ?? game?.mode ?? map?.parent ?? null;
  const duration = match != null
    ? formatSeriesClock(match.duration_s, { h: t("common.duration.h"), m: t("common.duration.m"), s: t("common.duration.s") })
    : null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent variant="panel" className="max-h-[90vh] w-[95vw] max-w-[1100px]">
        <DialogHeader variant="panel">
          <DialogTitle className="flex items-center gap-2.5">
            {mode?.image_path ? (
              <Image src={mode.image_path} alt="" width={26} height={26} aria-hidden />
            ) : null}
            {(match != null ? mapWithModeName(match.map, match.mode) : null) ?? mapName}
          </DialogTitle>
          <div className="flex flex-wrap items-center gap-x-4.5 gap-y-2">
            <span className="aqt-tnum flex items-center gap-2">
              <span className={cn(DIALOG_TEAM, SIDE_TEXT[1])}>{shownNames.one}</span>
              <span className={cn("text-heading font-bold", SIDE_TEXT[1])}>{shownScore?.one}</span>
              <span aria-hidden className={SCORE_SEP}>
                :
              </span>
              <span className={cn("text-heading font-bold", SIDE_TEXT[2])}>{shownScore?.two}</span>
              <span className={cn(DIALOG_TEAM, SIDE_TEXT[2])}>{shownNames.two}</span>
            </span>
            {match != null ? (
              <span className={cn(CARD_SUB, "ms-auto flex flex-wrap items-center gap-x-3.5 gap-y-1.5")}>
                {duration ? (
                  <span className={DIALOG_FACT}>
                    <Eyebrow>{t("encounters.match.playtime")}</Eyebrow>
                    <span className={DIALOG_FACT_VALUE}>{duration}</span>
                  </span>
                ) : null}
                {game?.result_source != null ? (
                  <span className={DIALOG_FACT}>
                    <Eyebrow>{t("encounters.match.source")}</Eyebrow>
                    <span className={DIALOG_FACT_VALUE}>
                      {t(`encounters.game.source.${game.result_source}` as never)}
                    </span>
                  </span>
                ) : null}
                {match.log_name ? (
                  <span className={DIALOG_FACT}>
                    <Eyebrow>{t("encounters.match.logName")}</Eyebrow>
                    <span className={DIALOG_FACT_VALUE}>
                      <span className="truncate">{match.log_name}</span>
                    </span>
                  </span>
                ) : null}
                <span className={DIALOG_FACT}>
                  <RawLogStatus raw_status={match.raw_status} raw_available={match.raw_available} />
                  {match.raw_available ? (
                    <MatchLogIndicator
                      hasLogs
                      logs={[{ matchId: match.id, label: match.map?.name ?? undefined, rawAvailable: match.raw_available }]}
                    />
                  ) : null}
                </span>
                {showMatchLink ? (
                  <Link
                    href={`/matches/${match.id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 font-semibold text-[color:var(--aqt-teal)] transition-colors hover:underline"
                  >
                    <ExternalLink aria-hidden width={14} height={14} />
                    <span className="hidden sm:inline">{t("encounters.match.openNewTab")}</span>
                  </Link>
                ) : null}
              </span>
            ) : null}
          </div>
        </DialogHeader>
        <div className="flex-1 overflow-y-auto p-4">
          {matchQuery.isError ? (
            <PageStateCard state="error" onAction={() => void matchQuery.refetch()} />
          ) : matchQuery.data ? (
            <MatchStatistics match={matchQuery.data} />
          ) : (
            <div className="flex flex-col gap-2" aria-busy>
              {Array.from({ length: 8 }).map((_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
