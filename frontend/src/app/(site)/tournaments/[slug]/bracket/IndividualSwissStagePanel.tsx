"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ChevronRight, Crown } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { TournamentTeamCardFrame } from "@/components/TournamentTeamCard";
import { LinkTabs } from "@/components/kit/LinkTabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { cn } from "@/lib/utils";
import type { Stage, Tournament } from "@/types/tournament.types";

import { ViewSegment, readViewParam } from "../_components/ViewSegment";
import { individualRoundsQueryOptions } from "../_queries/individualSwiss";
import {
  buildRoundViews,
  currentRound,
  type RoundLobby,
  type RoundSeat
} from "../_views/individualRounds.model";
import { isStagePreview } from "./bracketData";
import type { BracketTabs } from "./bracketStages.model";

/**
 * An `individual_swiss` stage on the public bracket.
 *
 * Like `FfaStagePanel` it replaces `GroupStagePanel`: the teams are formed anew
 * every round and belong to no `tournament.team`, so there is no bracket and no
 * standings switch — the round's lobbies are the view (the personal table is
 * the Player standings tab). One request answers every round of the stage.
 */
export function IndividualSwissStagePanel({
  tournament,
  stage,
  bracketTabs
}: Readonly<{
  tournament: Tournament;
  stage: Stage;
  bracketTabs?: BracketTabs;
}>) {
  const t = useTranslations();
  const searchParams = useSearchParams();
  const roundsQuery = useQuery(individualRoundsQueryOptions(tournament, stage.id));
  const isPreview = isStagePreview(stage);
  const views = buildRoundViews(roundsQuery.data ?? []);
  const latest = currentRound(views);
  const rounds = views.map((view) => String(view.round));
  const selected = readViewParam(searchParams, "round", rounds, String(latest));
  const view = views.find((candidate) => String(candidate.round) === selected);

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-4 py-4">
        {bracketTabs && bracketTabs.items.length > 1 ? (
          <div className="flex flex-wrap items-center gap-3">
            <LinkTabs
              variant="pill"
              items={bracketTabs.items}
              activeKey={bracketTabs.activeKey}
              ariaLabel={t("tournamentDetail.stageTabsLabel")}
            />
            {isPreview && <Badge variant="outline">{t("common.bracketPreview")}</Badge>}
          </div>
        ) : (
          <h3 className="truncate text-lg font-semibold text-[color:var(--aqt-fg)]">
            {stage.name}
            {isPreview && (
              <Badge variant="outline" className="ml-2 align-middle">
                {t("common.bracketPreview")}
              </Badge>
            )}
          </h3>
        )}
        {views.length > 1 ? (
          <ViewSegment
            param="round"
            defaultValue={String(latest)}
            hideOnMobile={false}
            label={t("tournamentDetail.individualRounds.roundsLabel")}
            options={views.map((candidate) => ({
              value: String(candidate.round),
              label: t("tournamentDetail.individualRounds.round", { round: candidate.round })
            }))}
          />
        ) : view ? (
          <Eyebrow as="p" tone="dim">
            {t("tournamentDetail.individualRounds.round", { round: view.round })}
          </Eyebrow>
        ) : null}
      </div>

      <div className="p-4">
        {roundsQuery.isPending ? (
          <Skeleton className="h-64 w-full rounded-xl" />
        ) : roundsQuery.isError ? (
          <div className="space-y-3 py-8 text-center text-[color:var(--aqt-fg-muted)]">
            <p>{t("tournamentDetail.pageState.initialError.title")}</p>
            <Button variant="outline" onClick={() => void roundsQuery.refetch()}>
              {t("tournamentDetail.pageState.retry")}
            </Button>
          </div>
        ) : !view ? (
          <div className="space-y-1 py-8 text-center text-[color:var(--aqt-fg-muted)]">
            <p className="font-semibold">{t("tournamentDetail.individualRounds.empty.title")}</p>
            <p>{t("tournamentDetail.individualRounds.empty.description")}</p>
          </div>
        ) : (
          <div className="space-y-6">
            {view.lobbies.map((lobby) => (
              <LobbyCard
                key={lobby.encounterId}
                tournament={tournament}
                lobby={lobby}
                linked={!isPreview}
              />
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

function LobbyCard({
  tournament,
  lobby,
  linked
}: Readonly<{ tournament: Tournament; lobby: RoundLobby; linked: boolean }>) {
  const t = useTranslations("tournamentDetail.individualRounds");
  const title = t("match", { number: lobby.number, bestOf: lobby.bestOf });

  return (
    <section className="min-w-0 space-y-2" aria-label={title}>
      <h4 className="px-1 text-base font-semibold">
        {linked ? (
          <Link
            href={`/encounters/${lobby.encounterId}`}
            aria-label={t("open", { number: lobby.number })}
            className="inline-flex items-center gap-1 text-[color:var(--aqt-fg)] underline-offset-4 hover:text-[color:var(--aqt-teal)] hover:underline"
          >
            {title}
            <ChevronRight aria-hidden className="size-4" />
          </Link>
        ) : (
          title
        )}
      </h4>
      <div className="grid gap-3 md:grid-cols-2">
        {lobby.seats.map((seat) => (
          <SeatCard key={seat.participation_id} tournament={tournament} lobby={lobby} seat={seat} />
        ))}
      </div>
    </section>
  );
}

function SeatCard({
  tournament,
  lobby,
  seat
}: Readonly<{ tournament: Tournament; lobby: RoundLobby; seat: RoundSeat }>) {
  const t = useTranslations("tournamentDetail.individualRounds");
  const ontology = useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;

  return (
    <TournamentTeamCardFrame
      slot={seat.slot === 1 ? 1 : 2}
      name={seat.name}
      metricValue={
        <span
          className={cn(
            "font-display",
            lobby.winnerSlot === seat.slot && "text-[color:var(--aqt-teal)]"
          )}
        >
          {lobby.scored ? seat.score : "\u2014"}
        </span>
      }
    >
      <ul className="divide-y divide-[color:var(--aqt-overlay-border)] px-3.5 py-1">
        {seat.members.map((member) => (
          <li
            key={member.workspace_member_id}
            className="flex min-w-0 items-center gap-2 py-2 text-caption"
          >
            <PlayerRoleIcon role={member.role} ontology={ontology} size={16} decorative />
            <span className="min-w-0 truncate font-medium">
              <bdi>{member.display_name}</bdi>
            </span>
            {member.is_captain ? (
              <>
                <Crown aria-hidden className="size-3 shrink-0 text-[color:var(--aqt-amber)]" />
                <span className="sr-only">{t("captain")}</span>
              </>
            ) : null}
            {member.rank != null ? (
              <span
                className="aqt-tnum ml-auto shrink-0 text-[color:var(--aqt-fg-dim)]"
                title={t("rank")}
              >
                {member.rank}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </TournamentTeamCardFrame>
  );
}
