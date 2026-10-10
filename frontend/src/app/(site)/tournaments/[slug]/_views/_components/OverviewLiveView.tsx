"use client";

import { useTranslations } from "next-intl";

import { useFormatter } from "@/lib/datetime/client";
import { isEncounterCompleted } from "@/lib/encounter/status";
import type { Encounter } from "@/types/encounter.types";
import type { FfaLobby } from "@/types/ffa.types";
import type { StreamEntry } from "@/types/stream.types";

import { CardLink, OverviewCard, OverviewStreamCard } from "./OverviewCards";
import { StatTile } from "./RegistrationSummary";

/**
 * B: while it is being played (§3B). The matches carry the page; the right
 * column is the timeline, the official broadcast and the reference tail.
 */
export function OverviewLiveView({
  encounters,
  lobbies,
  overviewHref,
  officialStream,
  participantsOnAir,
  nowBlock,
  miniBracket,
  groupTable,
  aboutCard,
  phasesCard,
  formatCard,
  linksCard
}: Readonly<{
  encounters: readonly Encounter[];
  lobbies: readonly FfaLobby[];
  overviewHref: string;
  officialStream: StreamEntry | undefined;
  participantsOnAir: number;
  nowBlock: React.ReactNode;
  miniBracket: React.ReactNode;
  groupTable: React.ReactNode;
  aboutCard: React.ReactNode;
  phasesCard: React.ReactNode;
  formatCard: React.ReactNode;
  linksCard: React.ReactNode;
}>) {
  const t = useTranslations();
  const format = useFormatter();

  // A lobby is one match of its stage: duels and lobbies share the tile.
  const playedCount =
    encounters.filter(isEncounterCompleted).length + lobbies.filter(isEncounterCompleted).length;
  const matchesCount = encounters.length + lobbies.length;

  return (
    <div className="grid gap-4 lg:grid-cols-[7fr_3fr]">
      <div className="grid content-start gap-4">
        {nowBlock}
        {miniBracket}
        {groupTable}
        {aboutCard}
      </div>
      <div className="grid content-start gap-4">
        {/* ⑦ The same timeline, second orientation. */}
        {phasesCard}
        {/* Poster only, no autoplay: the broadcast dock already owns the
            player, and a second one would fight it for the audio. */}
        {officialStream ? (
          <OverviewStreamCard
            official={officialStream}
            href={`${overviewHref}/stream`}
            action={
              <CardLink href={`${overviewHref}/stream`}>
                {participantsOnAir > 0
                  ? t("tournamentDetail.overview.stream.participants", {
                      count: participantsOnAir
                    })
                  : t("tournamentDetail.overview.stream.open")}
              </CardLink>
            }
            viewers={
              officialStream.viewer_count != null
                ? t("tournamentDetail.overview.stream.viewers", {
                    count: format.number(officialStream.viewer_count)
                  })
                : null
            }
          />
        ) : null}
        {/* Teams and players are the header's stamps; the only figure this card
            adds while play runs is how far along it is. */}
        <OverviewCard title={t("tournamentDetail.overview.numbers.title")}>
          <StatTile
            label={t("tournamentDetail.overview.numbers.played")}
            value={`${playedCount}/${matchesCount}`}
          />
        </OverviewCard>
        {/* Reference tail, identical in the completed branch: what this
            tournament is, then where the organizer's channels are. */}
        {formatCard}
        {linksCard}
      </div>
    </div>
  );
}
