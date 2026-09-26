"use client";

import { useTranslations } from "next-intl";

import { useMinuteClock } from "@/hooks/useMinuteClock";

import { visibleTournamentLinks } from "../_components/TournamentLinkChips";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentOverviewSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import styles from "../TournamentDetail.module.css";
import { OverviewCompletedView } from "./_components/OverviewCompletedView";
import { OverviewLiveView } from "./_components/OverviewLiveView";
import { OverviewMatchBlock } from "./_components/OverviewMatchBlock";
import { OverviewRegistrationView } from "./_components/OverviewRegistrationView";
import {
  OverviewFormatCard,
  OverviewLinksCard,
  OverviewPhasesCard
} from "./_components/OverviewSideCards";
import { OverviewGroupTable, OverviewMiniBracket } from "./_components/OverviewStageCards";
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

  // ---- shared right-column blocks -----------------------------------------
  const phasesCard = <OverviewPhasesCard tournament={tournament} />;
  const formatCard = <OverviewFormatCard tournament={tournament} />;
  /* `null` when nothing renders: `visibleTournamentLinks` owns that judgement,
     so a tournament whose only link is the official stream does not get a
     heading over an empty row — and the registration branch reads this very
     `null` to decide whether it has an aside column at all. */
  const linksCard =
    visibleTournamentLinks(tournament.links).length > 0 ? (
      <OverviewLinksCard tournament={tournament} />
    ) : null;

  // ---- the mini bracket / group table (§3 ⑥) -------------------------------
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

  const groupTable =
    data.hasGroupTable && stage !== null ? (
      <OverviewGroupTable
        stage={stage}
        stageStandings={data.stageStandings}
        overviewHref={overviewHref}
      />
    ) : null;

  const nowBlock = (
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
        formatCard={formatCard}
        linksCard={linksCard}
      />
    ) : variant === "live" ? (
      <OverviewLiveView
        tournament={tournament}
        encounters={data.encounters}
        overviewHref={overviewHref}
        officialStream={data.officialStream}
        participantsOnAir={data.participantsOnAir}
        nowBlock={nowBlock}
        miniBracket={miniBracket}
        groupTable={groupTable}
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
        formatCard={formatCard}
        linksCard={linksCard}
      />
    );

  const content = (
    <section className={styles.publicDataPage} aria-label={t("common.overview")}>
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
