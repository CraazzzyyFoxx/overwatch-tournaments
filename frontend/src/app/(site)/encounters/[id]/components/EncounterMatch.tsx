import React from "react";
import { getTranslations } from "next-intl/server";
import Image from "next/image";
import { Card } from "@/components/ui/card";
import { Match } from "@/types/encounter.types";
import { Dialog, DialogContent, DialogHeader, DialogTrigger } from "@/components/ui/dialog";
import encounterService from "@/services/encounter.service";
import { VisuallyHidden } from "@radix-ui/react-visually-hidden";
import MatchStatsSection from "@/app/(site)/matches/[id]/components/MatchStatsSection";
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";

const EncounterMatch = async ({ match }: { match: Match }) => {
  const t = await getTranslations();
  const mapImagePath: string = match.map ? match.map?.image_path : "";
  const data = await encounterService.getMatch(match.id);

  const tournamentGrid = data.encounter?.tournament?.division_grid_version ?? null;

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Card className="overflow-hidden relative h-[115px] max-w-[230px]">
          <Image src={mapImagePath} alt={t("encounters.match.mapAlt")} fill={true} />
          <h4 className="absolute bottom-0 left-0 m-2 text-xl font-semibold tracking-tight text-white p-1">
            {match.map?.name}
          </h4>
        </Card>
      </DialogTrigger>
      <DialogContent className="flex max-h-[90vh] w-[95vw] max-w-[1100px] flex-col gap-0 overflow-hidden p-0">
        <VisuallyHidden>
          <DialogHeader />
        </VisuallyHidden>
        <div className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-2 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-4 pr-14">
            <div className="flex items-center gap-2.5">
              <Image
                src={data.map?.gamemode.image_path || ""}
                alt={data.map?.gamemode.name || t("encounters.match.gamemodeAlt")}
                height={32}
                width={32}
              />
              <h4 className="text-lg font-semibold tracking-tight">{data.map?.name}</h4>
            </div>
            <div className="flex items-center gap-2">
              <span className="max-w-[160px] truncate text-sm font-semibold text-[color:var(--aqt-teal)]">
                {data.home_team.name}
              </span>
              <span className="aqt-tnum text-xl font-bold text-[color:var(--aqt-teal)]">{data.score.home}</span>
              <span className="text-[color:var(--aqt-fg-dim)]">:</span>
              <span className="aqt-tnum text-xl font-bold text-[color:var(--aqt-rose)]">{data.score.away}</span>
              <span className="max-w-[160px] truncate text-sm font-semibold text-[color:var(--aqt-rose)]">
                {data.away_team.name}
              </span>
            </div>
            <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[color:var(--aqt-fg-muted)]">
              <span className="inline-flex items-center gap-1.5">
                <span className="text-[color:var(--aqt-fg-faint)]">{t("encounters.match.playtime")}</span>
                <span className="aqt-tnum font-semibold text-[color:var(--aqt-fg)]">
                  {Math.floor(match.time / 60)}m {(match.time % 60).toFixed(0)}s
                </span>
              </span>
              {match.log_name ? (
                <span className="inline-flex items-center gap-1.5">
                  <span className="aqt-tnum">{match.log_name}</span>
                  <MatchLogIndicator
                    hasLogs={Boolean(match.log_name)}
                    logs={[{ matchId: match.id, label: match.map?.name ?? undefined }]}
                  />
                </span>
              ) : null}
              <Link
                href={`/matches/${data.id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 font-semibold text-[color:var(--aqt-teal)] hover:underline"
              >
                <ExternalLink className="h-4 w-4" />
                <span className="hidden sm:inline">{t("encounters.match.openNewTab")}</span>
              </Link>
            </div>
          </div>
        <div className="flex-1 overflow-y-auto p-4">
          <MatchStatsSection match={data} tournamentGrid={tournamentGrid} />
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default EncounterMatch;
