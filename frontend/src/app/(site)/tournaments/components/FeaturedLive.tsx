"use client";

import React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Users } from "lucide-react";

import {
  type LiveTournamentGroup,
  currentMapName,
  relativeTime,
  teamInitials,
} from "./tournaments-helpers";

const stopPropagation = (event: React.MouseEvent) => event.stopPropagation();

const FeaturedTournamentCard = ({
  group,
  small = false,
}: {
  group: LiveTournamentGroup;
  small?: boolean;
}) => {
  const router = useRouter();
  const { tournament, current, encounters } = group;

  const stageName = current.stage?.name ?? null;
  const mapName = currentMapName(current);
  const players = tournament.participants_count ?? 0;

  const onCardClick = (event: React.MouseEvent) => {
    if ((event.target as HTMLElement).closest("a")) return;
    router.push(`/tournaments/${tournament.id}`);
  };

  return (
    <article
      className={`feat-card live${small ? " small" : ""}`}
      onClick={onCardClick}
    >
      <div className="feat-glow" />
      <div className="feat-hex" />

      <div className="feat-top">
        <div>
          <span className="feat-id">
            #{tournament.number}
            {tournament.is_league ? " · League" : ""}
          </span>
          <h3 className="feat-name">{tournament.name}</h3>
        </div>
        <span className="status-pill live">
          <span className="dot" />
          {stageName ? `Live · ${stageName}` : "Live"}
        </span>
      </div>

      <div className="feat-meta">
        <span className="meta-pill">
          <Users width={11} height={11} />
          <span className="v">{players}</span> players
        </span>
        <span className="meta-pill">
          <span className="v">{encounters.length}</span> live now
        </span>
      </div>

      <div className="feat-progress">
        <div className="feat-stat">
          <span className="l">Matches</span>
          <span className="v">
            {encounters.length}
            <em> live</em>
          </span>
          <span className="s">{players} players</span>
        </div>
        <div className="feat-stat">
          <span className="l">Stage</span>
          <span className="v">{stageName ?? "Live"}</span>
          <span className="s">in progress</span>
        </div>
      </div>

      <div className="feat-now">
        <div className="now-lbl">
          <span className="k">
            <span
              className="live-dot"
              style={{ marginRight: 4, width: 6, height: 6 }}
            />
            NOW
          </span>
          <span className="v">{stageName ?? `BO${current.best_of}`}</span>
        </div>
        <div className="vs">
          <div className="team">
            <span className="av t1">{teamInitials(current.home_team?.name)}</span>
            <span className="nm">{current.home_team?.name ?? "TBD"}</span>
          </div>
          <span className="score">
            <span className="em">{current.score?.home ?? 0}</span>
            <span className="sep">·</span>
            {current.score?.away ?? 0}
          </span>
          <div className="team right">
            <span className="av t2">{teamInitials(current.away_team?.name)}</span>
            <span className="nm">{current.away_team?.name ?? "TBD"}</span>
          </div>
        </div>
        {mapName && <span className="map-pill">{mapName}</span>}
      </div>

      <div className="feat-foot">
        <div className="left">
          <span className="lead-team">
            Started {relativeTime(current.started_at)}
          </span>
        </div>
        <div className="right">
          <Link
            href={`/tournaments/${tournament.id}/bracket`}
            className="tn-btn"
            onClick={stopPropagation}
          >
            Bracket
            <ArrowRight width={11} height={11} />
          </Link>
          <Link
            href={`/tournaments/${tournament.id}`}
            className="tn-btn primary"
            onClick={stopPropagation}
          >
            Open
            <ArrowRight width={11} height={11} />
          </Link>
        </div>
      </div>
    </article>
  );
};

const FeaturedLive = ({ groups }: { groups: LiveTournamentGroup[] }) => {
  if (groups.length === 0) return null;

  const [first, second] = groups;

  return (
    <section>
      <div className="section-head">
        <h2>
          <span
            className="live-dot"
            style={{ width: 7, height: 7, marginRight: 0 }}
          />
          Live right now
          <span className="count-tag">
            {groups.length} event{groups.length === 1 ? "" : "s"}
          </span>
        </h2>
        <span className="meta">Auto-refresh · 30s</span>
      </div>
      <div className="featured-grid">
        <FeaturedTournamentCard group={first} />
        {second && <FeaturedTournamentCard group={second} small />}
      </div>
    </section>
  );
};

export default FeaturedLive;
