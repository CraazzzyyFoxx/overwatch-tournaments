import React from "react";
import encounterService from "@/services/encounter.service";
import { Metadata } from "next";
import Image from "next/image";
import MatchStatsSection from "@/app/(site)/matches/[id]/components/MatchStatsSection";
import { Card, CardHeader } from "@/components/ui/card";
import { getTranslations } from "next-intl/server";
import { SITE_NAME, SITE_URL } from "@/config/site";

export const dynamic = 'force-dynamic';

export async function generateMetadata(props: {
  params: Promise<{ id: number }>;
}): Promise<Metadata> {
  const params = await props.params;
  const match = await encounterService.getMatch(params.id);
  const t = await getTranslations();

  const matchTitle = t("matches.meta.matchTitle", {
    home: match.home_team.name,
    away: match.away_team.name
  });
  const matchDescription = t("matches.meta.matchDescription", {
    home: match.home_team.name,
    away: match.away_team.name,
    siteName: SITE_NAME
  });

  return {
    title: `${matchTitle} | ${SITE_NAME}`,
    description: matchDescription,
    openGraph: {
      title: `${matchTitle} | ${SITE_NAME}`,
      description: matchDescription,
      url: SITE_URL,
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
  const t = await getTranslations();

  const tournamentGrid = match.encounter?.tournament?.division_grid_version ?? null;

  let tournament_name = `${match?.encounter?.tournament.number}`;
  if (match?.encounter?.tournament.is_league) {
    tournament_name = match?.encounter?.tournament.name;
  }
  const stageLabel =
    match?.encounter?.stage_item?.name ??
    match?.encounter?.stage?.name ??
    t("matches.unassignedStage");

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <div className="flex flex-row gap-8 items-center">
            <div className="flex flex-row gap-4 items-center">
              <Image
                src={match.map?.gamemode.image_path || ""}
                alt={match.map?.gamemode.name || t("matches.gamemode")}
                height={40}
                width={40}
              />
              <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">{match.map?.name}</h4>
            </div>
            <div className="flex flex-row gap-4">
              <div className="flex flex-col text-right">
                <p className="leading-7 text-[color:var(--aqt-teal)]">{match.home_team.name}</p>
                <h4 className="scroll-m-20 text-xl font-semibold tracking-tight text-[color:var(--aqt-teal)]">
                  {match.score.home}
                </h4>
              </div>
              <div className="flex items-end">
                <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">:</h4>
              </div>
              <div className="flex flex-col text-left">
                <p className="leading-7  text-[color:var(--aqt-rose)]">{match.away_team.name}</p>
                <h4 className="scroll-m-20 text-xl font-semibold tracking-tight text-[color:var(--aqt-rose)]">
                  {match.score.away}
                </h4>
              </div>
            </div>
            <div className="flex flex-row gap-4">
              <div className="flex flex-col text-right">
                <p className="leading-7">{t("matches.playtime")}</p>
                <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">
                  {Math.floor(match.time / 60)}m {(match.time % 60).toFixed(0)}s
                </h4>
              </div>
            </div>

            <div className="flex flex-col text-right">
              <p className="leading-7">{t("matches.logName")}</p>
              <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">{match.log_name}</h4>
            </div>
            <div className="flex flex-col">
              <p className="leading-7 ">{t("common.tournament")}</p>
              <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">{tournament_name}</h4>
            </div>
            <div className="flex flex-col">
              <p className="leading-7 ">{t("common.stage")}</p>
              <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">{stageLabel}</h4>
            </div>
          </div>
        </CardHeader>
      </Card>
      <MatchStatsSection match={match} tournamentGrid={tournamentGrid} />
    </div>
  );
};

export default EncounterPage;
