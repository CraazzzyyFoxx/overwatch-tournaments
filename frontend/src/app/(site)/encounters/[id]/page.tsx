import React from "react";
import encounterService from "@/services/encounter.service";
import EncounterTeamCard from "@/app/(site)/encounters/[id]/components/EncounterTeamCard";
import { Metadata } from "next";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import EncounterMatch from "@/app/(site)/encounters/[id]/components/EncounterMatch";
import { Swords, ArrowLeft } from "lucide-react";
import { SITE_NAME } from "@/config/site";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { MapVeto } from "@/app/(site)/encounters/[id]/components/MapVeto";

export const dynamic = 'force-dynamic';

export async function generateMetadata(props: {
  params: Promise<{ id: number }>;
}): Promise<Metadata> {
  const params = await props.params;
  const encounter = await encounterService.getEncounter(params.id);

  return {
    title: `${encounter.home_team.name} vs ${encounter.away_team.name} | ${SITE_NAME}`,
    description: `Overview for ${encounter.home_team.name} vs ${encounter.away_team.name} on ${SITE_NAME}.`,
    openGraph: {
      title: `${encounter.home_team.name} vs ${encounter.away_team.name} | ${SITE_NAME}`,
      description: `Overview for ${encounter.home_team.name} vs ${encounter.away_team.name} on ${SITE_NAME}.`,
      url: "https://aqt.craazzzyyfoxx.me",
      type: "website",
      siteName: SITE_NAME,
      locale: "en_US"
    }
  };
}

const EncounterPage = async (props: { params: Promise<{ id: number }> }) => {
  const params = await props.params;
  const encounter = await encounterService.getEncounter(params.id);
  const homeTeamState =
    encounter.score.home === encounter.score.away
      ? "Tie"
      : encounter.score.home > encounter.score.away
        ? "Winner"
        : "Loser";
  const awayTeamState =
    encounter.score.home === encounter.score.away
      ? "Tie"
      : encounter.score.home < encounter.score.away
        ? "Winner"
        : "Loser";
  let name = `${encounter.tournament.number}`;
  if (encounter.tournament.is_league) {
    name = encounter.tournament.name;
  }
  const stageLabel = encounter.stage_item?.name ?? encounter.stage?.name ?? "Unassigned";
  const tournamentGrid = encounter.tournament.division_grid_version ?? null;

  return (
    <div className="flex flex-col gap-8">
      <div>
        <Button variant="outline" asChild>
          <Link href="/encounters">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to encounters
          </Link>
        </Button>
      </div>
      <Card>
        <CardContent className="flex flex-row gap-8 p-4">
          <div className="flex flex-row gap-4 items-center">
            <Swords height={40} width={40} />
            <div className="flex flex-col">
              <p className="leading-7 ">Tournament</p>
              <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">{name}</h4>
            </div>
            <div className="flex flex-col">
              <p className="leading-7 ">Stage</p>
              <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">
                {stageLabel}
              </h4>
            </div>
          </div>
        </CardContent>
      </Card>
      <div className="py-8 grid xs:grid-cols-1 xl:grid-cols-3 gap-8">
        <EncounterTeamCard
          team={encounter.home_team}
          isHome={true}
          tournamentGrid={tournamentGrid}
        />
        <Card>
          <CardHeader>
            <div className="flex gap-4">
              <div className="flex-1 text-right">
                <p className="scroll-m-20 text-2xl font-semibold tracking-tight text-[#16e5b4]">
                  {homeTeamState}
                </p>
                <h4 className="scroll-m-20 text-xl font-semibold tracking-tight text-[#16e5b4]">
                  {encounter.score.home}
                </h4>
              </div>
              <div className="flex items-end">
                <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">:</h4>
              </div>
              <div className="flex-1 text-left">
                <p className="scroll-m-20 text-2xl font-semibold tracking-tight text-[#ff4655]">
                  {awayTeamState}
                </p>
                <h4 className="scroll-m-20 text-xl font-semibold tracking-tight text-[#ff4655]">
                  {encounter.score.away}
                </h4>
              </div>
            </div>
          </CardHeader>
          <CardContent className="grid xs:grid-cols-1 xs1:grid-cols-2 md:grid-cols-3 xl:grid-cols-2 gap-4">
            {encounter.matches.map((match) => (
              <EncounterMatch key={match.id} match={match} />
            ))}
          </CardContent>
        </Card>
        <EncounterTeamCard
          team={encounter.away_team}
          isHome={false}
          tournamentGrid={tournamentGrid}
        />
      </div>
      <MapVeto encounterId={encounter.id} />
    </div>
  );
};

export default EncounterPage;
