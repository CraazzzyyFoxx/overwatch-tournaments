"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { ArrowRight, Users } from "lucide-react";

import TeamName from "@/components/TeamName";
import { SectionHead } from "@/components/match/EncounterAtoms";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { StatusDot } from "@/components/ui/status-dot";
import { duelSeats, seatTeam } from "@/lib/encounter/seats";
import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { tournamentHref } from "@/lib/tournament/url";
import { cn } from "@/lib/utils";
import type { TeamFormation } from "@/types/tournament.types";
import { type LiveTournamentGroup, currentMapName } from "./tournaments-helpers";

const LIVE_DOT = "text-[color:var(--aqt-status-live)]";
const STAT_VALUE = "font-display text-title leading-none font-bold tabular-nums text-[color:var(--aqt-fg)]";
const STAT_SUB = "text-label text-[color:var(--aqt-fg-dim)]";
const TEAM_NAME = "truncate text-caption font-semibold text-[color:var(--aqt-fg)]";

const FeaturedTournamentCard = ({
  group,
  small = false,
}: {
  group: LiveTournamentGroup;
  small?: boolean;
}) => {
  const t = useTranslations();
  const format = useFormatter();
  const now = useMinuteClock();
  const { tournament, current, encounters } = group;
  const [seatOne, seatTwo] = duelSeats(current.teams);

  const stageName = current.stage?.name ?? null;
  const mapName = currentMapName(current);
  const players = tournament.participants_count ?? 0;

  return (
    <Card asChild className="flex flex-col overflow-hidden transition-colors hover:border-[color:var(--aqt-border-3)]">
      <article>
        <div className="flex items-start justify-between gap-3.5 px-5.5 pb-4 pt-5.5">
          <div>
            <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">
              {tournament.is_league ? t("common.league") : ""}
              {tournament.team_formation &&
                `${tournament.is_league ? " · " : ""}${t(`common.${tournament.team_formation as TeamFormation}`)}`}
            </span>
            {/* The card used to navigate from an `onClick` on the <article>, so
                keyboard users could not reach it and AT never announced a target.
                A stretched overlay link is not an option here: the footer's
                Bracket/Open buttons could never sit above the overlay. The title
                carries the link instead. */}
            <h3
              className={cn(
                "mt-1.5 max-w-[90%] font-display font-bold",
                small ? "text-title" : "text-headline"
              )}
            >
              <Link
                href={tournamentHref(tournament)}
                className="text-inherit no-underline hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
              >
                {tournament.name}
              </Link>
            </h3>
          </div>
          <TournamentStatusPill status="live">
            {stageName ? `${t("common.live")} · ${stageName}` : t("common.live")}
          </TournamentStatusPill>
        </div>

        <p className="flex flex-wrap items-center gap-x-1.5 px-5.5 pb-4 text-caption text-[color:var(--aqt-fg-muted)]">
          <Users aria-hidden className="size-3 text-[color:var(--aqt-fg-faint)]" />
          <span className="font-semibold text-[color:var(--aqt-fg)]">{players}</span> {t("common.players")}
          <span aria-hidden className="text-[color:var(--aqt-fg-dim)]">·</span>
          <span className="font-semibold text-[color:var(--aqt-fg)]">{encounters.length}</span>{" "}
          {t("tournamentsList.featured.liveNow")}
        </p>

        <div className="grid grid-cols-2 gap-4 border-t border-[color:var(--aqt-border)] px-5.5 pt-3.5">
          <div className="flex flex-col gap-0.5">
            <Eyebrow>{t("common.matches")}</Eyebrow>
            <span className={STAT_VALUE}>
              {encounters.length}
              <span className="font-normal text-[color:var(--aqt-fg-muted)]">
                {" "}
                {t("tournamentsList.featured.liveWord")}
              </span>
            </span>
            <span className={STAT_SUB}>
              {t("tournamentsList.featured.playersCount", { count: players })}
            </span>
          </div>
          <div className="flex flex-col gap-0.5">
            <Eyebrow>{t("common.stage")}</Eyebrow>
            <span className={STAT_VALUE}>{stageName ?? t("common.live")}</span>
            <span className={STAT_SUB}>{t("tournamentsList.featured.inProgress")}</span>
          </div>
        </div>

        <div className="flex items-center gap-3.5 px-5.5 pb-4.5 pt-5">
          <div className="flex flex-col gap-px">
            <Eyebrow className={cn("inline-flex items-center gap-1", LIVE_DOT)}>
              <StatusDot pulse />
              {t("tournamentsList.featured.now")}
            </Eyebrow>
            <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
              {stageName ?? `BO${current.best_of}`}
            </span>
          </div>
          <div className="flex flex-1 items-center justify-center gap-3.5">
            <div className="flex min-w-0 items-center gap-2">
              <TeamName
                team={seatTeam(seatOne)}
                fallback={t("common.tbd")}
                size="sm"
                nameClassName={TEAM_NAME}
              />
            </div>
            <span className="font-display text-title font-bold tabular-nums text-[color:var(--aqt-fg)]">
              {seatOne?.score ?? 0}
              <span className="mx-1.5 text-[color:var(--aqt-fg-faint)]">·</span>
              {seatTwo?.score ?? 0}
            </span>
            <div className="flex min-w-0 items-center gap-2">
              <TeamName
                team={seatTeam(seatTwo)}
                fallback={t("common.tbd")}
                size="sm"
                nameClassName={TEAM_NAME}
                reverse
              />
            </div>
          </div>
          {mapName && (
            <span className="aqt-tnum text-label text-[color:var(--aqt-fg-muted)]">{mapName}</span>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-[color:var(--aqt-border)] px-5.5 py-3.5">
          <span className="text-label text-[color:var(--aqt-fg-muted)]">
            {t("tournamentsList.featured.started", {
              time: current.started_at && now !== null ? format.relativeTime(new Date(current.started_at), now) : "—"
            })}
          </span>
          <div className="flex gap-2">
            <Button asChild variant="outline" size="xs">
              <Link href={tournamentHref(tournament, "/bracket")}>
                {t("common.bracket")}
                <ArrowRight aria-hidden />
              </Link>
            </Button>
            <Button asChild variant="accent" size="xs">
              <Link href={tournamentHref(tournament)}>
                {t("common.open")}
                <ArrowRight aria-hidden />
              </Link>
            </Button>
          </div>
        </div>
      </article>
    </Card>
  );
};

const FeaturedLive = ({ groups }: { groups: LiveTournamentGroup[] }) => {
  const t = useTranslations();

  if (groups.length === 0) return null;

  const [first, second] = groups;

  return (
    <section>
      <SectionHead
        title={
          <span className="flex items-center gap-2.5">
            <StatusDot pulse className={LIVE_DOT} />
            {t("tournamentsList.featured.liveRightNow")}
            <span className="aqt-tnum text-caption font-normal text-[color:var(--aqt-fg-faint)]">
              {t("tournamentsList.featured.eventsCount", { count: groups.length })}
            </span>
          </span>
        }
        meta={t("tournamentsList.featured.autoRefresh")}
      />
      <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <FeaturedTournamentCard group={first} />
        {second && <FeaturedTournamentCard group={second} small />}
      </div>
    </section>
  );
};

export default FeaturedLive;
