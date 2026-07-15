"use client";

import { useTranslations } from "next-intl";

import EncountersTable, {
  getEncountersQueryPresentation,
  useEncountersTableController
} from "@/components/EncountersTable";

import styles from "../TournamentDetail.module.css";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentMatchesSkeleton } from "../_components/TournamentSkeletons";
import { useTournamentQuery } from "../_hooks/useTournamentClientData";

export interface TournamentEncounterPageProps {
  tournamentId: number;
  page: number;
  search: string;
}

const TournamentEncountersPage = ({ tournamentId, page, search }: TournamentEncounterPageProps) => {
  const t = useTranslations();
  const tournamentQuery = useTournamentQuery(tournamentId);
  const tournament = tournamentQuery.data;
  const workspaceId = tournament ? tournament.workspace_id : undefined;
  const controller = useEncountersTableController({
    initialPage: page,
    search,
    tournamentId,
    workspaceId,
    enabled: tournament !== undefined
  });
  const rows = controller.encountersQuery.data ? controller.encountersQuery.data.results : [];
  const presentation = getEncountersQueryPresentation({
    data: controller.encountersQuery.data,
    itemCount: rows.length,
    isPending: controller.encountersQuery.isPending,
    isError: controller.encountersQuery.isError,
    isFetching: controller.encountersQuery.isFetching
  });

  if (!tournament) {
    if (tournamentQuery.isError) {
      return (
        <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
      );
    }
    return <TournamentMatchesSkeleton />;
  }

  if (presentation.initialState === "error") {
    return (
      <TournamentPageState
        state="initial-error"
        onRetry={() => void controller.encountersQuery.refetch()}
      />
    );
  }

  const encounters = controller.encountersQuery.data;
  if (
    presentation.initialState === "skeleton" ||
    presentation.contentState === null ||
    !encounters
  ) {
    return <TournamentMatchesSkeleton />;
  }

  const content = (
    <section className={styles.publicDataPage} aria-labelledby="tournament-matches-title">
      <header className={styles.pageHeading}>
        <div className={styles.pageHeadingCopy}>
          <span className={styles.pageEyebrow}>
            {t("tournamentDetail.publicPages.matches.eyebrow")}
          </span>
          <div className={styles.pageTitleRow}>
            <h2 className={styles.pageTitle} id="tournament-matches-title">
              {t("common.matches")}
            </h2>
            <span className={styles.pageCount}>{encounters.total}</span>
          </div>
          <p className={styles.pageContext}>{t("tournamentDetail.publicPages.matches.context")}</p>
        </div>
        {presentation.showUpdating ? (
          <span className={styles.updating} role="status" aria-live="polite">
            {t("tournamentDetail.pageState.updating")}
          </span>
        ) : null}
      </header>

      <EncountersTable
        encounters={encounters}
        currentPage={controller.currentPage}
        onSetPage={controller.setCurrentPage}
        search={search}
        searchInputRef={controller.searchInputRef}
        onSearchInput={controller.onSearchInput}
        hideTournament
      />

      {presentation.contentState === "empty" ? (
        <TournamentPageState
          state="empty"
          title={t("tournamentDetail.publicPages.matches.emptyTitle")}
          description={t("tournamentDetail.publicPages.matches.emptyDescription")}
        />
      ) : null}
    </section>
  );

  if (presentation.showRefreshError) {
    return (
      <TournamentPageState
        state="refresh-error"
        onRetry={() => void controller.encountersQuery.refetch()}
        isUpdating={controller.encountersQuery.isFetching}
      >
        {content}
      </TournamentPageState>
    );
  }

  return content;
};

export default TournamentEncountersPage;
