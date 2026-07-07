"use client";

import React from "react";

import { PageHero, HeroCoord, HeroStat } from "@/components/site/PageHero";

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
    <PageHero
      eyebrow={
        <>
          <HeroCoord>OWT // Tournaments</HeroCoord>
          {workspaceName ? <HeroCoord>Sector · {workspaceName}</HeroCoord> : null}
        </>
      }
      title={
        <>
          All <em>tournaments</em> in one place
        </>
      }
      lede="From draft to crown: track every event your community has run. Live brackets, locked rosters, and crowned champions — all in one ledger."
      aside={
        <div className="grid grid-cols-3 gap-6">
          <HeroStat
            label={
              <span className="inline-flex items-center gap-1.5">
                {liveEvents > 0 ? (
                  <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--aqt-rose)] [animation:aqtPulse_2s_ease-in-out_infinite]" />
                ) : null}
                Live now
              </span>
            }
            value={
              liveEvents > 0 ? (
                <span className="text-[color:var(--aqt-teal)]">{liveEvents}</span>
              ) : (
                liveEvents
              )
            }
            sub={
              liveMatches > 0
                ? `${liveMatches} match${liveMatches === 1 ? "" : "es"} in flight`
                : "No matches in flight"
            }
          />
          <HeroStat
            label="Total tournaments"
            value={totalTournaments}
            sub={`${activeTournaments} active`}
          />
          <HeroStat
            label="Players"
            value={totalPlayers}
            sub={`${totalTeams} teams balanced`}
          />
        </div>
      }
    />
  );
};

export default TournamentsHero;
