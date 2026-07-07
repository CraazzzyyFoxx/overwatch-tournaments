import React, { ReactNode } from "react";
import Image from "next/image";
import { Card } from "@/components/ui/card";
import { Match } from "@/types/encounter.types";
import { Dialog, DialogContent, DialogHeader, DialogTrigger } from "@/components/ui/dialog";
import encounterService from "@/services/encounter.service";
import { VisuallyHidden } from "@radix-ui/react-visually-hidden";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import MatchTeamTable from "@/app/(site)/matches/[id]/components/MatchTeamTable";
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import MatchStatsChart from "@/app/(site)/encounters/[id]/components/MatchStatsChart";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";

const EncounterMatch = async ({ match }: { match: Match }) => {
  const mapImagePath: string = match.map ? match.map?.image_path : "";
  const data = await encounterService.getMatch(match.id);

  const maxHeroesHome: Record<number, number> = {};
  const maxHeroesAway: Record<number, number> = {};
  const maxHeroes: Record<number, number> = {};
  let maxRoundI = 0;
  for (let roundI = 0; roundI < data.rounds + 1; roundI++) {
    maxRoundI = Math.max(maxRoundI, roundI);
    maxHeroesHome[roundI] = data.home_team.players.reduce(
      (max, player) => Math.max(max, player.heroes[roundI] ? player.heroes[roundI].length : 0),
      0
    );
    maxHeroesAway[roundI] = data.away_team.players.reduce(
      (max, player) => Math.max(max, player.heroes[roundI] ? player.heroes[roundI].length : 0),
      0
    );
    maxHeroes[roundI] = Math.max(maxHeroesHome[roundI], maxHeroesAway[roundI]);
  }

  const tournamentGrid = data.encounter?.tournament?.division_grid_version ?? null;

  const tabsTriggers: ReactNode[] = [];
  const tabsContent: ReactNode[] = [];
  Object.keys(data.home_team.players[0].stats).forEach((key) => {
    if (key != "0") {
      tabsTriggers.push(<TabsTrigger value={key}>Round {key}</TabsTrigger>);
    }
    tabsContent.push(
      <TabsContent value={key}>
        <MatchTeamTable
          team={data.home_team}
          isHome={true}
          matchRound={parseInt(key)}
          maxHeroes={maxHeroes[parseInt(key)]}
          tournamentGrid={tournamentGrid}
        />
        <MatchTeamTable
          team={data.away_team}
          isHome={false}
          matchRound={parseInt(key)}
          maxHeroes={maxHeroes[parseInt(key)]}
          tournamentGrid={tournamentGrid}
        />
      </TabsContent>
    );
  });

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Card className="overflow-hidden relative h-[115px] max-w-[230px]">
          <Image src={mapImagePath} alt="Map" fill={true} />
          <h4 className="absolute bottom-0 left-0 m-2 text-xl font-semibold tracking-tight text-white p-1">
            {match.map?.name}
          </h4>
        </Card>
      </DialogTrigger>
      <DialogContent className="xl:min-w-fit min-h-fit p-0">
        <VisuallyHidden>
          <DialogHeader />
        </VisuallyHidden>
        <div className="flex flex-col">
          <div className="flex justify-between items-center p-4 mr-16">
            <div className="flex flex-row gap-8 items-center">
              <div className="flex flex-row gap-4 items-center">
                <Image
                  src={data.map?.gamemode.image_path || ""}
                  alt={data.map?.gamemode.name || "Gamemode"}
                  height={40}
                  width={40}
                />
                <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">
                  {data.map?.name}
                </h4>
              </div>
              <div className="flex flex-row gap-4">
                <div className="flex flex-col text-right">
                  <p className="leading-7 text-[color:var(--aqt-teal)]">{data.home_team.name}</p>
                  <h4 className="scroll-m-20 text-xl font-semibold tracking-tight text-[color:var(--aqt-teal)]">
                    {data.score.home}
                  </h4>
                </div>
                <div className="flex items-end">
                  <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">:</h4>
                </div>
                <div className="flex flex-col text-left">
                  <p className="leading-7  text-[color:var(--aqt-rose)]">{data.away_team.name}</p>
                  <h4 className="scroll-m-20 text-xl font-semibold tracking-tight text-[color:var(--aqt-rose)]">
                    {data.score.away}
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
                <div className="flex items-center justify-end gap-2">
                  <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">
                    {match.log_name}
                  </h4>
                  <MatchLogIndicator
                    hasLogs={Boolean(match.log_name)}
                    logs={match.log_name ? [{ matchId: match.id, label: match.map?.name ?? undefined }] : undefined}
                  />
                </div>
              </div>
            </div>
            <Link href={`/matches/${data.id}`} target="_blank" rel="noopener noreferrer">
              <div className="flex gap-2 scroll-m-20 text-xl font-semibold tracking-tight">
                <ExternalLink />
                Open in New Tab
              </div>
            </Link>
          </div>
          <Tabs defaultValue="0">
            <TabsList className="ml-8">
              <TabsTrigger value="0">All Match</TabsTrigger>
              {...tabsTriggers}
            </TabsList>
            {...tabsContent}
          </Tabs>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default EncounterMatch;
