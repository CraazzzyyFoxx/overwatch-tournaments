"use client";

import { useRef } from "react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { DataPagination } from "@craazzzyyfoxx/admin-kit/ui/data-pagination";
import { PageStateCard } from "@/components/ui/page-state-card";
import { EncountersDataTable } from "@/components/EncountersTable";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import { useGameBoundParams } from "@/components/workspace/scope-pill-store";
import { useGameDescriptors } from "@/hooks/useGameDescriptors";
import { useGameScope } from "@/hooks/useGameScope";
import { ALL_DISCIPLINES, showsGameMarks, type GameScopeInit } from "@/lib/site/discipline-scope";
import type { StatsScope } from "@/lib/site/stats-scope";
import { cn } from "@/lib/utils";

import Loading from "../loading";
import {
  DEFAULT_FILTERS,
  ENCOUNTERS_PAGE_SIZE,
  GAME_SCOPED_FILTERS,
  hasActiveFilters,
  type EncountersUrlState
} from "./encounters.helpers";
import { useEncountersFilters } from "./useEncountersFilters";
import { useEncountersData, type EncountersSeed } from "./useEncountersData";
import { EncountersHero } from "./EncountersHero";
import { EncountersActiveFilters, EncountersToolbar } from "./EncountersToolbar";
import { EncountersInsights } from "./EncountersInsights";

type EncountersClientProps = {
  /** `null` when the server read nothing (an unreadable game) or its read failed: the browser reads instead. */
  seed: EncountersSeed | null;
  initial: GameScopeInit;
  initialUrl: EncountersUrlState;
  scope: StatsScope;
};

/** The URL params of one game's tournament/stage: a game picked in the scope pill drops them (ruling R5). */
const GAME_SCOPED_PARAMS = Object.keys(GAME_SCOPED_FILTERS);

/**
 * The encounters index (spec §5, multi): every game under "all games", one game under a game. Filter/URL state and
 * the reads it drives live in `useEncountersFilters` / `useEncountersData`; this is the layout: the hero's global
 * numbers, one toolbar, the chips of what narrows, then the list or the summary under the same filters.
 */
export default function EncountersClient({ seed, initial, initialUrl, scope }: Readonly<EncountersClientProps>) {
  const t = useTranslations();
  const format = useFormatter();
  const gameScope = useGameScope({ initial });
  useGameBoundParams(GAME_SCOPED_PARAMS);
  const { resolution } = gameScope;
  const discipline = gameScope.game;
  const ready = resolution?.game.kind === "all" || resolution?.game.kind === "game";
  const unavailable = resolution?.game.kind === "invalid" || resolution?.game.kind === "empty";
  // "all" or the game once readable, `null` otherwise: another game drops the game-bound filters and returns to the
  // first page; leaving an unavailable state reads them from the URL again.
  const gameKey = ready ? (discipline ?? ALL_DISCIPLINES) : null;
  const controls = useEncountersFilters(initialUrl, gameKey, unavailable);
  const { effectiveFilters, page, view } = controls;
  const { listQuery, overviewQuery, countsQuery, insightsQuery, tournamentsLookupQuery } = useEncountersData({
    seed,
    initial: initialUrl,
    effectiveFilters,
    page,
    view,
    scope,
    discipline,
    enabled: ready
  });
  const descriptors = useGameDescriptors();
  const marks = resolution !== null && showsGameMarks(resolution, gameScope.games ?? []) ? descriptors : undefined;
  // The page turn and the histogram land the reader back at the top of the results, under the sticky header.
  const resultsRef = useRef<HTMLDivElement>(null);
  const toResults = () => resultsRef.current?.scrollIntoView({ block: "start" });

  if (unavailable) {
    return <GameScopeControl scope={gameScope} variant="multi" dropParams={GAME_SCOPED_PARAMS} headingLevel={1} />;
  }
  if (!ready) {
    return gameScope.isError ? (
      <PageStateCard state="error" headingLevel={1} description={t("common.loadError")} onAction={gameScope.refetch} />
    ) : (
      <Loading />
    );
  }

  const tournaments = tournamentsLookupQuery.data ?? [];
  // The order is not a filter: a reset keeps it.
  const clearFilters = () => controls.applyFilters({ ...DEFAULT_FILTERS, sort: effectiveFilters.sort });
  const rows = listQuery.data?.results ?? [];
  const total = listQuery.data?.total ?? 0;

  const list = () => {
    if (listQuery.isError) return <PageStateCard state="error" onAction={() => void listQuery.refetch()} />;
    if (!rows.length && !listQuery.isFetching) {
      const filtered = hasActiveFilters(effectiveFilters);
      return <PageStateCard state={filtered ? "filtered-empty" : "empty"} onAction={filtered ? clearFilters : undefined} />;
    }
    return (
      <>
        {/* The previous page stays on screen while the next one loads, dimmed: not yet the answer. */}
        <div className={cn("transition-opacity", listQuery.isFetching && rows.length > 0 && "opacity-60")}>
          <EncountersDataTable rows={rows} loading={listQuery.isFetching && !rows.length} games={marks} />
        </div>
        {rows.length ? (
          <DataPagination
            page={page}
            totalPages={Math.max(1, Math.ceil(total / ENCOUNTERS_PAGE_SIZE))}
            onPageChange={(next) => {
              controls.setPage(next);
              toResults();
            }}
            leading={t("encounters.list.showing", {
              start: format.number((page - 1) * ENCOUNTERS_PAGE_SIZE + 1),
              end: format.number(Math.min(page * ENCOUNTERS_PAGE_SIZE, total)),
              total: format.number(total)
            })}
          />
        ) : null}
      </>
    );
  };

  return (
    <div className="space-y-4">
      <EncountersHero overview={overviewQuery.data} />

      <div ref={resultsRef} className="scroll-mt-[var(--aqt-header-h)] space-y-3">
        <EncountersToolbar
          controls={controls}
          counts={countsQuery.data?.counts}
          tournaments={tournaments}
          gameBound={discipline !== null}
        />
        <EncountersActiveFilters controls={controls} tournaments={tournaments} />

        {view === "insights" ? (
          <EncountersInsights
            query={insightsQuery}
            filtered={hasActiveFilters({ ...effectiveFilters, status: null })}
            onClearFilters={clearFilters}
            onPickCloseness={(start, end) => {
              controls.patchFilters({ closeness_min: start, closeness_max: end });
              controls.setView("list");
              toResults();
            }}
          />
        ) : (
          <section aria-label={t("encounters.list.label")} aria-busy={listQuery.isFetching} className="space-y-3">
            {list()}
          </section>
        )}
      </div>
    </div>
  );
}
