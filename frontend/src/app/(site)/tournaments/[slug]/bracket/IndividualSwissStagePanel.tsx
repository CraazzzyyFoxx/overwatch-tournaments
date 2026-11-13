"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ChevronDown, ChevronRight, ChevronsDownUp, ChevronsUpDown } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { TournamentTeamCardFrame, TournamentTeamTable } from "@/components/TournamentTeamCard";
import { LinkTabs } from "@/components/kit/LinkTabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Card } from "@craazzzyyfoxx/admin-kit/ui/card";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useFormatter } from "@/lib/datetime/client";
import { resolveDivisionFromRank } from "@/lib/divisions/grid";
import type { TeamRosterPlayer } from "@/lib/player";
import { ratedDimension, type RoleOntology } from "@/lib/roster/ontology";
import { toRoleRef } from "@/lib/roster/role-ref";
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
 * Lobbies open collapsed (team headers and the score only), so a round fits on
 * screen; a lobby, or the whole round, expands to the rosters.
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
  const ontology = useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;
  // Encounter ids are unique across rounds, so switching rounds needs no reset.
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(() => new Set());
  const isPreview = isStagePreview(stage);
  const views = buildRoundViews(roundsQuery.data ?? []);
  const latest = currentRound(views);
  const rounds = views.map((view) => String(view.round));
  const selected = readViewParam(searchParams, "round", rounds, String(latest));
  const view = views.find((candidate) => String(candidate.round) === selected);
  const allExpanded =
    view !== undefined &&
    view.lobbies.length > 0 &&
    view.lobbies.every((lobby) => expanded.has(lobby.encounterId));

  const toggleLobby = (encounterId: number) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (!next.delete(encounterId)) next.add(encounterId);
      return next;
    });
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
        <div className="flex flex-wrap items-center justify-between gap-3">
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
          {view && view.lobbies.length > 0 ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setExpanded(allExpanded ? new Set() : new Set(view.lobbies.map((lobby) => lobby.encounterId)))
              }
            >
              {allExpanded ? <ChevronsDownUp aria-hidden /> : <ChevronsUpDown aria-hidden />}
              {allExpanded
                ? t("tournamentDetail.individualRounds.collapseAll")
                : t("tournamentDetail.individualRounds.expandAll")}
            </Button>
          ) : null}
        </div>
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
          <div className="space-y-5">
            {view.lobbies.map((lobby) => (
              <LobbyCard
                key={lobby.encounterId}
                tournament={tournament}
                ontology={ontology}
                lobby={lobby}
                linked={!isPreview}
                open={expanded.has(lobby.encounterId)}
                onToggle={() => toggleLobby(lobby.encounterId)}
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
  ontology,
  lobby,
  linked,
  open,
  onToggle
}: Readonly<{
  tournament: Tournament;
  ontology: RoleOntology | null;
  lobby: RoundLobby;
  linked: boolean;
  open: boolean;
  onToggle: () => void;
}>) {
  const t = useTranslations("tournamentDetail.individualRounds");
  const title = t("match", { number: lobby.number, bestOf: lobby.bestOf });
  const [first, second] = lobby.seats;
  const seatCard = (seat: RoundSeat | undefined) =>
    seat ? (
      <SeatCard
        tournament={tournament}
        ontology={ontology}
        seat={seat}
        collapsed={!open}
        mirrored={seat === second}
        lost={lobby.winnerSlot !== null && lobby.winnerSlot !== seat.slot}
      />
    ) : (
      <div />
    );

  return (
    <section className="min-w-0 space-y-2" aria-label={title}>
      <div className="flex items-center gap-1 px-1">
        <h4 className="text-base font-semibold">
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
        <Button
          variant="ghost"
          size="icon-sm"
          className="ml-auto"
          aria-expanded={open}
          aria-label={t(open ? "collapseMatch" : "expandMatch", { number: lobby.number })}
          onClick={onToggle}
        >
          <ChevronDown aria-hidden className={cn("transition-transform", open && "rotate-180")} />
        </Button>
      </div>
      {/* Score between the cards; on a phone the cards stack and the score sits between them. */}
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-start">
        {seatCard(first)}
        <LobbyScore lobby={lobby} first={first} second={second} open={open} />
        {seatCard(second)}
      </div>
    </section>
  );
}

/** "VS" over the series score; a pending lobby has no score yet, only the "VS". */
function LobbyScore({
  lobby,
  first,
  second,
  open
}: Readonly<{ lobby: RoundLobby; first?: RoundSeat; second?: RoundSeat; open: boolean }>) {
  const t = useTranslations("tournamentDetail.individualRounds");
  const scored = lobby.scored && first !== undefined && second !== undefined;
  const tone = (seat: RoundSeat) =>
    lobby.winnerSlot === null
      ? "text-[color:var(--aqt-fg)]"
      : lobby.winnerSlot === seat.slot
        ? "text-[color:var(--aqt-teal)]"
        : "text-[color:var(--aqt-fg-dim)]";

  return (
    <div
      className={cn(
        "flex min-w-20 flex-col items-center justify-center gap-0.5 md:self-stretch",
        // Expanded, the score stays level with the card headers instead of the roster middle.
        open && "md:max-h-24"
      )}
    >
      <span className="font-display text-caption font-semibold tracking-[0.2em] text-[color:var(--aqt-fg-faint)]">
        {t("versus")}
      </span>
      {scored ? (
        <>
          <span aria-hidden className="font-display text-3xl font-bold leading-none tabular-nums">
            <span className={tone(first)}>{first.score}</span>
            <span className="mx-1.5 text-[color:var(--aqt-fg-faint)]">:</span>
            <span className={tone(second)}>{second.score}</span>
          </span>
          <span className="sr-only">{t("score", { first: first.score, second: second.score })}</span>
        </>
      ) : null}
    </div>
  );
}

/**
 * A lobby's team as the standard roster card, the average rank in the header. The pair reads by
 * position (the second card mirrored); the result reads from the score and the loser's dimmed card.
 */
function SeatCard({
  tournament,
  ontology,
  seat,
  collapsed,
  mirrored,
  lost
}: Readonly<{
  tournament: Tournament;
  ontology: RoleOntology | null;
  seat: RoundSeat;
  collapsed: boolean;
  mirrored: boolean;
  /** The lobby is finished and this team is behind. */
  lost: boolean;
}>) {
  const t = useTranslations("tournamentDetail.individualRounds");
  const format = useFormatter();
  const workspaceGrid = useDivisionGrid(tournament.discipline);
  // The same grid `RosterRank` names the crest from: the tournament's own, else the workspace's.
  const grid = tournament.division_grid_version ?? workspaceGrid;
  const dimension = (ontology && ratedDimension(ontology)?.code) ?? "";
  const ranks = seat.members.flatMap((member) => (member.rank != null ? [member.rank] : []));
  const avgRank = ranks.length > 0 ? ranks.reduce((sum, rank) => sum + rank, 0) / ranks.length : null;
  const captain = seat.members.find((member) => member.is_captain);
  // A round team is a snapshot of workspace members: no profile link, newcomer flags or subs; the division comes from the rank.
  const players: TeamRosterPlayer[] = seat.members.map((member) => ({
    id: member.workspace_member_id,
    user_id: member.workspace_member_id,
    name: member.display_name,
    display: { name: member.display_name, tag: null, canonical: null, snapshot: null },
    role: toRoleRef(member.role, null, dimension),
    rank: member.rank,
    division: resolveDivisionFromRank(grid, member.rank),
    is_newcomer: false,
    is_newcomer_role: false,
    is_substitution: false,
    related_player_id: null
  }));

  return (
    <TournamentTeamCardFrame
      mirrored={mirrored}
      className={cn(lost && "opacity-70 hover:opacity-100")}
      name={seat.name}
      collapsed={collapsed}
      metricLabel={avgRank != null ? t("avgRank") : undefined}
      metricValue={avgRank != null ? format.number(avgRank, { maximumFractionDigits: 0 }) : undefined}
    >
      <TournamentTeamTable
        players={players}
        tournamentGrid={tournament.division_grid_version}
        discipline={tournament.discipline}
        ontology={ontology}
        captainUserId={captain?.workspace_member_id}
      />
    </TournamentTeamCardFrame>
  );
}
