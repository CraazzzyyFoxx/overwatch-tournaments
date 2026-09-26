"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { ArrowRight, Users } from "lucide-react";

import TeamName from "@/components/TeamName";
import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { tournamentHref } from "@/lib/tournament/url";
import type { TeamFormation } from "@/types/tournament.types";
import { type LiveTournamentGroup, currentMapName } from "./tournaments-helpers";

const FeaturedTournamentCard = ({
  group,
  small = false,
}: {
  group: LiveTournamentGroup;
  small?: boolean;
}) => {
  const t = useTranslations();
  const format = useFormatter();
  const { tournament, current, encounters } = group;

  const stageName = current.stage?.name ?? null;
  const mapName = currentMapName(current);
  const players = tournament.participants_count ?? 0;

  return (
    <article className={`feat-card live${small ? " small" : ""}`}>
      <div aria-hidden className="feat-glow" />
      <div aria-hidden className="feat-hex" />

      <div className="feat-top">
        <div>
          <span className="feat-id">
            {tournament.is_league ? t("common.league") : ""}
            {tournament.team_formation &&
              `${tournament.is_league ? " · " : ""}${t(`common.${tournament.team_formation as TeamFormation}`)}`}
          </span>
          {/* The card used to navigate from an `onClick` on the <article>, so
              keyboard users could not reach it and AT never announced a target.
              A stretched overlay link is not an option here: `.feat-foot` is its
              own stacking context, so the footer's Bracket/Open buttons could
              never sit above the overlay. The title carries the link instead. */}
          <h3 className="feat-name">
            <Link
              href={tournamentHref(tournament)}
              className="text-inherit no-underline outline-none hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
            >
              {tournament.name}
            </Link>
          </h3>
        </div>
        <TournamentStatusPill status="live">
          {stageName ? `${t("common.live")} · ${stageName}` : t("common.live")}
        </TournamentStatusPill>
      </div>

      <div className="feat-meta">
        <span className="meta-pill">
          <Users aria-hidden width={11} height={11} />
          <span className="v">{players}</span> {t("common.players")}
        </span>
        <span className="meta-pill">
          <span className="v">{encounters.length}</span> {t("tournamentsList.featured.liveNow")}
        </span>
      </div>

      <div className="feat-progress">
        <div className="feat-stat">
          <span className="l">{t("common.matches")}</span>
          <span className="v">
            {encounters.length}
            <em> {t("tournamentsList.featured.liveWord")}</em>
          </span>
          <span className="s">
            {t("tournamentsList.featured.playersCount", { count: players })}
          </span>
        </div>
        <div className="feat-stat">
          <span className="l">{t("common.stage")}</span>
          <span className="v">{stageName ?? t("common.live")}</span>
          <span className="s">{t("tournamentsList.featured.inProgress")}</span>
        </div>
      </div>

      <div className="feat-now">
        <div className="now-lbl">
          <span className="k">
            <span
              aria-hidden
              className="live-dot"
              style={{ marginRight: 4, width: 6, height: 6 }}
            />
            {t("tournamentsList.featured.now")}
          </span>
          <span className="v">{stageName ?? `BO${current.best_of}`}</span>
        </div>
        <div className="vs">
          <div className="team">
            <TeamName
              team={current.home_team}
              fallback={t("common.tbd")}
              size="sm"
              nameClassName="nm"
            />
          </div>
          <span className="score">
            <span className="em">{current.score?.home ?? 0}</span>
            <span className="sep">·</span>
            {current.score?.away ?? 0}
          </span>
          <div className="team right">
            <TeamName
              team={current.away_team}
              fallback={t("common.tbd")}
              size="sm"
              nameClassName="nm"
              reverse
            />
          </div>
        </div>
        {mapName && <span className="map-pill">{mapName}</span>}
      </div>

      <div className="feat-foot">
        <div className="left">
          <span className="lead-team">
            {t("tournamentsList.featured.started", {
              time: current.started_at ? format.relativeTime(new Date(current.started_at)) : "—"
            })}
          </span>
        </div>
        <div className="right">
          <Link href={tournamentHref(tournament, "/bracket")} className="tn-btn">
            {t("common.bracket")}
            <ArrowRight aria-hidden width={11} height={11} />
          </Link>
          <Link href={tournamentHref(tournament)} className="tn-btn primary">
            {t("common.open")}
            <ArrowRight aria-hidden width={11} height={11} />
          </Link>
        </div>
      </div>
    </article>
  );
};

const FeaturedLive = ({ groups }: { groups: LiveTournamentGroup[] }) => {
  const t = useTranslations();

  if (groups.length === 0) return null;

  const [first, second] = groups;

  return (
    <section>
      <div className="section-head">
        <h2>
          <span
            aria-hidden
            className="live-dot"
            style={{ width: 7, height: 7, marginRight: 0 }}
          />
          {t("tournamentsList.featured.liveRightNow")}
          <span className="count-tag">
            {t("tournamentsList.featured.eventsCount", { count: groups.length })}
          </span>
        </h2>
        <span className="meta">{t("tournamentsList.featured.autoRefresh")}</span>
      </div>
      <div className="featured-grid">
        <FeaturedTournamentCard group={first} />
        {second && <FeaturedTournamentCard group={second} small />}
      </div>
    </section>
  );
};

export default FeaturedLive;
