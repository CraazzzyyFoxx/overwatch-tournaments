import React, { ReactNode } from "react";
import encounterService from "@/services/encounter.service";
import { Metadata } from "next";
import Image from "next/image";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import MatchTeamTable from "@/app/(site)/matches/[id]/components/MatchTeamTable";
import { Card, CardHeader } from "@/components/ui/card";
import { SITE_NAME } from "@/config/site";

export const dynamic = 'force-dynamic';

export async function generateMetadata(props: {
  params: Promise<{ id: number }>;
}): Promise<Metadata> {
  const params = await props.params;
  const match = await encounterService.getMatch(params.id);

  return {
    title: `${match.home_team.name} vs ${match.away_team.name} | ${SITE_NAME}`,
    description: `Overview for ${match.home_team.name} vs ${match.away_team.name} on ${SITE_NAME}.`,
    openGraph: {
      title: `${match.home_team.name} vs ${match.away_team.name} | ${SITE_NAME}`,
      description: `Overview for ${match.home_team.name} vs ${match.away_team.name} on ${SITE_NAME}.`,
      url: "https://aqt.craazzzyyfoxx.me",
      type: "website",
      siteName: SITE_NAME,
      images: [
        {
          url: match.map?.image_path || "",
          width: 1200,
          height: 630
        }
      ],
      locale: "en_US"
    }
  };
}

const EncounterPage = async (props: { params: Promise<{ id: number }> }) => {
  const params = await props.params;
  const match = await encounterService.getMatch(params.id);

  const maxHeroesHome: Record<number, number> = {};
  const maxHeroesAway: Record<number, number> = {};
  const maxHeroes: Record<number, number> = {};
  let maxRoundI = 0;
  for (let roundI = 0; roundI < match.rounds + 1; roundI++) {
    maxRoundI = Math.max(maxRoundI, roundI);
    maxHeroesHome[roundI] = match.home_team.players.reduce(
      (max, player) => Math.max(max, player.heroes[roundI] ? player.heroes[roundI].length : 0),
      0
    );
    maxHeroesAway[roundI] = match.away_team.players.reduce(
      (max, player) => Math.max(max, player.heroes[roundI] ? player.heroes[roundI].length : 0),
      0
    );
    maxHeroes[roundI] = Math.max(maxHeroesHome[roundI], maxHeroesAway[roundI]);
  }

  const tournamentGrid = match.encounter?.tournament?.division_grid_version ?? null;

  let tournament_name = `${match?.encounter?.tournament.number}`;
  if (match?.encounter?.tournament.is_league) {
    tournament_name = match?.encounter?.tournament.name;
  }
  const stageLabel =
    match?.encounter?.stage_item?.name ?? match?.encounter?.stage?.name ?? "Unassigned";

  const tabsTriggers: ReactNode[] = [];
  const tabsContent: ReactNode[] = [];
  Object.keys(match.home_team.players[0].stats).forEach((key) => {
    if (key != "0") {
      tabsTriggers.push(<TabsTrigger value={key}>Round {key}</TabsTrigger>);
    }
    tabsContent.push(
      <TabsContent value={key}>
        <MatchTeamTable
          team={match.home_team}
          isHome={true}
          matchRound={parseInt(key)}
          maxHeroes={maxHeroes[parseInt(key)]}
          tournamentGrid={tournamentGrid}
        />
        <MatchTeamTable
          team={match.away_team}
          isHome={false}
          matchRound={parseInt(key)}
          maxHeroes={maxHeroes[parseInt(key)]}
          tournamentGrid={tournamentGrid}
        />
      </TabsContent>
    );
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-row gap-8 items-center">
          <div className="flex flex-row gap-4 items-center">
            <Image
              src={match.map?.gamemode.image_path || ""}
              alt={match.map?.gamemode.name || "Gamemode"}
              height={40}
              width={40}
            />
            <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">{match.map?.name}</h4>
          </div>
          <div className="flex flex-row gap-4">
            <div className="flex flex-col text-right">
              <p className="leading-7 text-[#16e5b4]">{match.home_team.name}</p>
              <h4 className="scroll-m-20 text-xl font-semibold tracking-tight text-[#16e5b4]">
                {match.score.home}
              </h4>
            </div>
            <div className="flex items-end">
              <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">:</h4>
            </div>
            <div className="flex flex-col text-left">
              <p className="leading-7  text-[#ff4655]">{match.away_team.name}</p>
              <h4 className="scroll-m-20 text-xl font-semibold tracking-tight text-[#ff4655]">
                {match.score.away}
              </h4>
            </div>
          </div>
          <div className="flex flex-row gap-4">
            <div className="flex flex-col text-right">
              <p className="leading-7">Playtime</p>
              <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">
                {Math.floor(match.time / 60)}m {(match.time % 60).toFixed(0)}s
              </h4>
            </div>
          </div>

          <div className="flex flex-col text-right">
            <p className="leading-7">Log name</p>
            <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">{match.log_name}</h4>
          </div>
          <div className="flex flex-col">
            <p className="leading-7 ">Tournament</p>
            <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">{tournament_name}</h4>
          </div>
          <div className="flex flex-col">
            <p className="leading-7 ">Stage</p>
            <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">
              {stageLabel}
            </h4>
          </div>
        </div>
      </CardHeader>
      <Tabs defaultValue="0">
        <TabsList className="ml-8">
          <TabsTrigger value="0">All Match</TabsTrigger>
          {...tabsTriggers}
        </TabsList>
        {...tabsContent}
      </Tabs>
    </Card>
  );
};

export default EncounterPage;
