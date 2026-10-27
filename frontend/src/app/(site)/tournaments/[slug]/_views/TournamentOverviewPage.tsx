"use client";

import { useTranslations } from "next-intl";

import { useMinuteClock } from "@/hooks/useMinuteClock";

import { visibleTournamentLinks } from "../_components/TournamentLinkChips";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentOverviewSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { OverviewCompletedView } from "./_components/OverviewCompletedView";
import { OverviewLiveView } from "./_components/OverviewLiveView";
import { OverviewMatchBlock } from "./_components/OverviewMatchBlock";
import { OverviewRegistrationView } from "./_components/OverviewRegistrationView";
import {
  OverviewAboutCard,
  OverviewFormatCard,
  OverviewLinksCard,
  OverviewPhasesCard
} from "./_components/OverviewSideCards";
import {
  OverviewFfaTable,
  OverviewGroupTable,
  OverviewMiniBracket
} from "./_components/OverviewStageCards";
import { useOverviewMatchPresenter } from "./useOverviewMatchPresenter";
import { useTournamentOverviewData } from "./useTournamentOverviewData";

type TournamentOverviewPageProps = {
  tournamentId: number;
  slug: string;
};

/**
 * The tournament's landing section — one component, three compositions keyed on
 * `status` (wireframes §3 A/B/C). The retired Schedule tab lives here as the
 * phase timeline (`#phases`); Maps is its own section.
 *
 * Everything below is assembly: the reads live in `useTournamentOverviewData`,
 * the per-encounter copy in `useOverviewMatchPresenter`, and each block in its
 * own file under `_components`. What stays here is the order the cards are
 * built in and which branch receives them, because that IS the page.
 */
export default function TournamentOverviewPage({
  tournamentId,
  slug
}: Readonly<TournamentOverviewPageProps>) {
  const t = useTranslations();
  // Null until hydration — recency text waits rather than disagree with SSR.
  const clockNow = useMinuteClock();

  const data = useTournamentOverviewData(tournamentId, slug);
  const presenter = useOverviewMatchPresenter({
    slug,
    stage: data.stage,
    stageId: data.stageId,
    roundShapeByStage: data.roundShapeByStage,
    liveTeamStreams: data.liveTeamStreams
  });

  const { tournament, variant, stage, presentation, primary } = data;

  if (!tournament || variant === null) {
    if (data.tournamentQuery.isError) {
      return (
        <TournamentPageState
          state="initial-error"
          onRetry={() => void data.tournamentQuery.refetch()}
        />
      );
    }
    return <TournamentOverviewSkeleton />;
  }

  if (presentation.initialState === "error") {
    return <TournamentPageState state="initial-error" onRetry={() => void primary?.refetch()} />;
  }
  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentOverviewSkeleton />;
  }

  const overviewHref = `/tournaments/${slug}`;

  // ---- shared blocks -------------------------------------------------------
  // No schedule, no timeline: and no heading over an empty block either.
  const phasesCard =
    (tournament.phase_schedule ?? []).length > 0 ? (
      <OverviewPhasesCard tournament={tournament} />
    ) : null;
  const formatCard = <OverviewFormatCard tournament={tournament} />;
  /* The description belongs to the WIDE column, not to the aside the format
     card sits in: it is prose, and prose in a 22rem column wraps every three
     words. `null` when the organizer wrote none. */
  const aboutCard = tournament.description?.trim() ? (
    <OverviewAboutCard description={tournament.description} />
  ) : null;
  /* `null` when nothing renders: `visibleTournamentLinks` owns that judgement,
     so a tournament whose only link is the official stream does not get a
     heading over an empty row. */
  const linksCard =
    visibleTournamentLinks(tournament.links).length > 0 ? (
      <OverviewLinksCard tournament={tournament} />
    ) : null;

  // ---- the mini bracket / group table / FFA lobbies (§3 ⑥) -----------------
  const miniBracket =
    data.hasMiniBracket && stage !== null ? (
      <OverviewMiniBracket
        stage={stage}
        roundGroups={data.roundGroups}
        stageEncounters={data.stageEncounters}
        roundShape={data.roundShape}
        overviewHref={overviewHref}
        presenter={presenter}
      />
    ) : null;

  // An FFA league's lobby tables take the group table's slot: both are the
  // stage's standings drawn in place of a bracket it does not have.
  const groupTable =
    stage === null ? null : data.hasGroupTable ? (
      <OverviewGroupTable
        stage={stage}
        stageStandings={data.stageStandings}
        overviewHref={overviewHref}
      />
    ) : data.hasFfaTable ? (
      <OverviewFfaTable stage={stage} lobbies={data.ffaLobbies} overviewHref={overviewHref} />
    ) : null;

  // An FFA stage with no duels has its lobby tables in place of matches; the
  // duel block's "nothing published" would contradict them.
  const nowBlock =
    data.encounters.length === 0 && data.hasFfaTable ? null : (
      <OverviewMatchBlock
        encounters={data.encounters}
        clockNow={clockNow}
        overviewHref={overviewHref}
        presenter={presenter}
      />
    );

  const branch =
    variant === "registration" ? (
      <OverviewRegistrationView
        tournament={tournament}
        registrationList={data.registrationList}
        registrations={data.registrations}
        overviewHref={overviewHref}
        clockNow={clockNow}
        aboutCard={aboutCard}
        formatCard={formatCard}
        linksCard={linksCard}
      />
    ) : variant === "live" ? (
      <OverviewLiveView
        nowBlock={nowBlock}
        miniBracket={miniBracket}
        groupTable={groupTable}
        aboutCard={aboutCard}
        phasesCard={phasesCard}
        formatCard={formatCard}
        linksCard={linksCard}
      />
    ) : (
      <OverviewCompletedView
        tournament={tournament}
        encounters={data.encounters}
        standings={data.standings}
        teams={data.teams}
        topHeroes={data.topHeroes}
        stage={stage}
        stageId={data.stageId}
        roundShape={data.roundShape}
        podiumNeedsStandings={data.podiumNeedsStandings}
        overviewHref={overviewHref}
        nowBlock={nowBlock}
        miniBracket={miniBracket}
        groupTable={groupTable}
        aboutCard={aboutCard}
        formatCard={formatCard}
        linksCard={linksCard}
      />
    );

  const content = (
    <section className="grid w-full min-w-0 max-w-full gap-4 *:min-w-0" aria-label={t("common.overview")}>
      {presentation.showUpdating ? <UpdatingBadge /> : null}
      {branch}
    </section>
  );

  if (presentation.showRefreshError) {
    return (
      <TournamentPageState
        state="refresh-error"
        onRetry={() => void primary?.refetch()}
        isUpdating={primary?.isFetching ?? false}
      >
        {content}
      </TournamentPageState>
    );
  }
  return content;
}
