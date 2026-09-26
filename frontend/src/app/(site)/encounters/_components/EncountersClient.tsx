"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { DataPagination } from "@/components/ui/data-pagination";
import { PageStateCard } from "@/components/ui/page-state-card";
import { EncountersDataTable, FULL_ENCOUNTER_COLUMNS } from "@/components/EncountersTable";
import type { PaginatedResponse } from "@/types/pagination.types";
import type { Encounter, EncounterOverview } from "@/types/encounter.types";

import { ENCOUNTERS_PAGE_SIZE, type EncounterFilterState } from "./encounters.helpers";
import { countLabel, hasActiveFilters } from "./encounters.model";
import { useEncountersFilters } from "./useEncountersFilters";
import { useEncountersData } from "./useEncountersData";
import { EncountersHero } from "./EncountersHero";
import { EncountersViewsBar } from "./EncountersViewsBar";
import { EncountersFilterBar } from "./EncountersFilterBar";
import { EncountersInsights } from "./EncountersInsights";
import { EncountersFeatured } from "./EncountersFeatured";
import { EncountersRail } from "./EncountersRail";
import styles from "./Encounters.module.css";

type EncountersClientProps = {
  initialData: PaginatedResponse<Encounter>;
  initialOverview: EncounterOverview;
  initialFilters: EncounterFilterState;
  initialPage: number;
  initialError?: string | null;
};

/**
 * The encounters index. Filter/URL state and the reads it drives live in
 * `useEncountersFilters` / `useEncountersData`; everything below is layout plus
 * the one piece of state neither owns — which page of the list is on screen.
 */
export default function EncountersClient({
  initialData,
  initialOverview,
  initialFilters,
  initialPage,
  initialError
}: Readonly<EncountersClientProps>) {
  const t = useTranslations();
  const format = useFormatter();
  const controls = useEncountersFilters(initialFilters, initialPage);
  const { effectiveFilters, page } = controls;
  const { listQuery, overviewQuery, tournamentsLookupQuery } = useEncountersData({
    initialData,
    initialOverview,
    initialFilters,
    initialPage,
    effectiveFilters,
    page
  });

  const overview = overviewQuery.data ?? initialOverview;
  const encounters = listQuery.data ?? initialData;
  const rows = encounters.results ?? [];
  const totalPages = Math.max(1, Math.ceil((encounters.total ?? 0) / ENCOUNTERS_PAGE_SIZE));
  const isFiltered = hasActiveFilters(effectiveFilters);
  const showingStart = rows.length ? (page - 1) * ENCOUNTERS_PAGE_SIZE + 1 : 0;
  const showingEnd = Math.min(page * ENCOUNTERS_PAGE_SIZE, encounters.total);

  const listBody = () => {
    if (listQuery.isError) {
      return <PageStateCard state="error" onAction={() => void listQuery.refetch()} />;
    }
    if (!rows.length && !listQuery.isFetching) {
      return (
        <PageStateCard
          state={isFiltered ? "filtered-empty" : "empty"}
          onAction={isFiltered ? controls.clearFilters : undefined}
        />
      );
    }
    return (
      <EncountersDataTable
        rows={rows}
        columns={FULL_ENCOUNTER_COLUMNS}
        loading={listQuery.isFetching && !rows.length}
      />
    );
  };

  return (
    <div className={styles.surface}>
      <EncountersHero overview={overview} />

      {initialError ? (
        <PageStateCard
          state="error"
          description={initialError}
          onAction={() => {
            void listQuery.refetch();
            void overviewQuery.refetch();
          }}
        />
      ) : null}

      <EncountersViewsBar
        filters={effectiveFilters}
        presetCounts={overview.preset_counts}
        onApplyFilters={controls.applyFilters}
      />

      <EncountersFilterBar
        filters={controls.filters}
        searchValue={controls.searchValue}
        kpis={overview.kpis}
        tournaments={tournamentsLookupQuery.data ?? []}
        onSearchChange={controls.setSearchValue}
        onPatch={controls.patchFilters}
      />

      <EncountersInsights overview={overview} />

      <EncountersFeatured overview={overview} />

      <section aria-label={t("encounters.list.title")}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>{t("encounters.list.title")}</h2>
          <span className={styles.sectionMeta}>
            {t("encounters.list.pageMeta", {
              page: String(page),
              total: String(totalPages),
              sort: effectiveFilters.sort
            })}
          </span>
        </div>
        <div className={styles.gridTable}>
          <div className="flex min-w-0 flex-col gap-3">
            {listBody()}
            <DataPagination
              page={page}
              totalPages={totalPages}
              onPageChange={controls.setPage}
              summary={t("encounters.list.showing", {
                start: String(showingStart),
                end: String(showingEnd),
                total: countLabel(format, encounters.total)
              })}
            />
          </div>

          <EncountersRail overview={overview} />
        </div>
      </section>
    </div>
  );
}
