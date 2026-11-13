import { Fragment, cache } from "react";
import { notFound } from "next/navigation";
import encounterService from "@/services/encounter.service";
import { isNotFoundError } from "@/lib/api/error";
import { cn } from "@/lib/utils";
import { Metadata } from "next";
import Image from "@/components/ui/image";
import MatchStatistics from "@/components/match/MatchStatistics";
import { observedScore } from "@/lib/encounter/detail";
import { Card, CardHeader } from "@craazzzyyfoxx/admin-kit/ui/card";
import TeamName from "@/components/TeamName";
import { EntityWorkspace } from "@/components/workspace/EntityWorkspace";
import { RawLogStatus } from "@/components/match/MatchLogIndicator";
import { getTranslations } from "next-intl/server";
import { SITE_NAME, SITE_URL } from "@/config/site";
import { seatsBySlot } from "@/lib/encounter/seats";
import { modeBeyondMap } from "@/lib/catalog/mode";

/** One accent per participant, in seat order; a lobby cycles through them. Full literals so Tailwind sees them. */
const ACCENT_CLASSES = [
  "text-[color:var(--aqt-teal)]",
  "text-[color:var(--aqt-rose)]",
  "text-[color:var(--aqt-amber)]",
  "text-[color:var(--aqt-violet)]"
];

// One read for the metadata and the page; an unknown id is the not-found page, not a 500.
const loadMatch = cache(async (id: number) => {
  try {
    return await encounterService.getMatch(id);
  } catch (error) {
    if (isNotFoundError(error)) notFound();
    throw error;
  }
});

export async function generateMetadata(props: {
  params: Promise<{ id: number }>;
}): Promise<Metadata> {
  const params = await props.params;
  const [match, t] = await Promise.all([loadMatch(params.id), getTranslations()]);

  const [home, away] = seatsBySlot(match.participants);
  const matchTitle = t("matches.meta.matchTitle", { home: home?.name ?? "—", away: away?.name ?? "—" });
  const matchDescription = t("matches.meta.matchDescription", {
    home: home?.name ?? "—",
    away: away?.name ?? "—",
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
      images: match.map?.image_path
        ? [{ url: match.map.image_path, width: 1200, height: 630 }]
        : undefined,
      locale: "en_US"
    }
  };
}

const EncounterPage = async (props: { params: Promise<{ id: number }> }) => {
  const params = await props.params;
  const [match, t] = await Promise.all([loadMatch(params.id), getTranslations()]);

  const participants = seatsBySlot(match.participants);
  const mode = match.mode ?? match.map?.parent ?? null;
  const modeAfterMap = modeBeyondMap(match.map, match.mode);
  const tournament_name = match?.encounter?.tournament.name;
  const stageLabel =
    match?.encounter?.stage_item?.name ??
    match?.encounter?.stage?.name ??
    t("common.unassignedStage");

  return (
    <div className="flex flex-col gap-4">
      <EntityWorkspace workspaceId={match.encounter?.tournament?.workspace_id} discipline={match.encounter?.discipline} />
      <Card>
        <CardHeader>
          <div className="flex flex-row gap-8 items-center">
            <div className="flex flex-row gap-4 items-center">
              {/* A map without a mode (every LoL map) or a mode without an image has no badge: never an empty src. */}
              {mode?.image_path ? (
                <Image
                  src={mode.image_path}
                  alt={mode.name || t("matches.gamemode")}
                  height={40}
                  width={40}
                />
              ) : null}
              <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">
                {match.map?.name}
                {/* A map shared by several modes does not name the one played. */}
                {modeAfterMap ? (
                  <span className="font-normal text-[color:var(--aqt-fg-dim)]"> · {modeAfterMap.name}</span>
                ) : null}
              </h4>
            </div>
            <div className="flex flex-row flex-wrap gap-4">
              {participants.map((participant, index) => {
                const accent = ACCENT_CLASSES[index % ACCENT_CLASSES.length];
                const logo = match.encounter?.teams?.find((seat) => seat.id === participant.encounter_team_id)?.team
                  ?.image_url;
                return (
                  <Fragment key={participant.encounter_team_id}>
                    {index > 0 ? (
                      <div className="flex items-end">
                        <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">:</h4>
                      </div>
                    ) : null}
                    <div className={cn("flex flex-col", index === 0 ? "text-right" : "text-left")}>
                      <TeamName
                        team={{ name: participant.name, image_url: logo }}
                        size="sm"
                        className={index === 0 ? "justify-end" : undefined}
                        nameClassName={cn("leading-7", accent)}
                      />
                      <h4 className={cn("scroll-m-20 text-xl font-semibold tracking-tight", accent)}>
                        {observedScore(participant) ?? "—"}
                      </h4>
                    </div>
                  </Fragment>
                );
              })}
            </div>
            <div className="flex flex-row gap-4">
              <div className="flex flex-col text-right">
                <p className="leading-7">{t("matches.playtime")}</p>
                <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">
                  {match.duration_s != null
                    ? `${Math.floor(match.duration_s / 60)}m ${(match.duration_s % 60).toFixed(0)}s`
                    : "—"}
                </h4>
              </div>
            </div>

            <div className="flex flex-col text-right">
              <p className="leading-7">{t("matches.logName")}</p>
              <h4 className="scroll-m-20 text-xl font-semibold tracking-tight">{match.log_name ?? "—"}</h4>
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
        <div className="space-y-2 px-6 pb-6 text-sm text-muted-foreground">
          {match.map_index == null ? <p>{t("encounters.history.unconfirmed")}</p> : null}
          <p><RawLogStatus raw_status={match.raw_status} raw_available={match.raw_available} /></p>
        </div>
      </Card>
      <MatchStatistics match={match} />
    </div>
  );
};

export default EncounterPage;
