"use client";

import React from "react";

interface TournamentsHeroProps {
  workspaceName?: string | null;
  liveEvents: number;
  liveMatches: number;
  totalTournaments: number;
  activeTournaments: number;
  totalPlayers: number;
  totalTeams: number;
}

const TournamentsHero = ({
  workspaceName,
  liveEvents,
  liveMatches,
  totalTournaments,
  activeTournaments,
  totalPlayers,
  totalTeams,
}: TournamentsHeroProps) => {
  return (
    <section className="hero">
      <div className="hex" />
      <div className="glow-1" />
      <div className="glow-2" />
      <div className="hero-grid">
        <div>
          <p className="crumb">
            {workspaceName ? `Workspace · ${workspaceName}` : "Workspace"}
          </p>
          <h1 className="h1">
            All <em>tournaments</em> in one place
          </h1>
          <p className="lede">
            From draft to crown: track every event your community has run. Live
            brackets, locked rosters, and crowned champions — all in one ledger.
          </p>
        </div>
        <div className="hero-stats">
          <div className="hero-stat">
            <span className="label">
              {liveEvents > 0 && <span className="live-dot" />}
              Live now
            </span>
            <span className="v">
              {liveEvents > 0 ? <em>{liveEvents}</em> : liveEvents}
            </span>
            <span className="sub">
              {liveMatches > 0
                ? `${liveMatches} match${liveMatches === 1 ? "" : "es"} in flight`
                : "No matches in flight"}
            </span>
          </div>
          <div className="hero-stat">
            <span className="label">Total tournaments</span>
            <span className="v">{totalTournaments}</span>
            <span className="sub">{activeTournaments} active</span>
          </div>
          <div className="hero-stat">
            <span className="label">Players</span>
            <span className="v">{totalPlayers}</span>
            <span className="sub">{totalTeams} teams balanced</span>
          </div>
        </div>
      </div>
    </section>
  );
};

export default TournamentsHero;
