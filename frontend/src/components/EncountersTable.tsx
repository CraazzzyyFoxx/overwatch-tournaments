"use client";

import React, { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { usePathname, useRouter } from "next/navigation";

import styles from "./EncountersTable.module.css";
// The `.aqt-matches` scope, moved out of globals.css and next to its consumer.
import "./EncountersTable.css";
import {
  getPublicPageQueryPresentation,
  type PublicPageQueryState
} from "@/lib/public-page-query-presentation";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import TeamName from "@/components/TeamName";
import {
  TournamentStatusPill,
  type TournamentStatusVariant
} from "@/components/tournaments/StatusPill";
import { DataPagination } from "@/components/ui/data-pagination";
import { SearchField } from "@/components/ui/search-field";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusDot } from "@/components/ui/status-dot";
import { cn } from "@/lib/utils";
import {
  getEncounterState,
  getEncounterWinner,
  isEncounterLive,
  type EncounterState
} from "@/lib/encounter/status";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import encounterService from "@/services/encounter.service";
import { Encounter } from "@/types/encounter.types";
import { PaginatedResponse } from "@/types/pagination.types";

const PER_PAGE = 15;
const SKELETON_ROWS = 8;

// Stable no-op subscriber: hydration never "changes" once it has happened, so
// the store has nothing to notify. Module scope keeps its identity stable.
const subscribeNoop = () => () => {};

export const getEncountersQueryPresentation = (state: PublicPageQueryState) =>
  getPublicPageQueryPresentation(state);

type EncounterRowKeyEvent = {
  key: string;
  target: unknown;
  currentTarget: unknown;
  preventDefault: () => void;
};

export function activateEncounterRowFromKeyboard(
  event: EncounterRowKeyEvent,
  navigate: () => void
): boolean {
  if (event.target !== event.currentTarget || !["Enter", " "].includes(event.key)) return false;

  event.preventDefault();
  navigate();
  return true;
}

/**
 * The one encounters list table for the whole site.
 *
 * The standalone `/encounters` page used to ship a second, independent 10-column
 * table with its own closeness bar, winner resolver and status derivation. This
 * table now covers both: the tournament detail page takes
 * `DEFAULT_ENCOUNTER_COLUMNS`, `/encounters` takes `FULL_ENCOUNTER_COLUMNS`.
 */
export type EncounterColumnKey =
  | "matchup"
  | "tournament"
  | "score"
  | "format"
  | "closeness"
  | "stage"
  | "maps"
  | "state"
  | "when"
  | "logs";

const DEFAULT_ENCOUNTER_COLUMNS: readonly EncounterColumnKey[] = [
  "matchup",
  "tournament",
  "score",
  "format",
  "closeness",
  "stage",
  "when",
  "logs"
];

export const FULL_ENCOUNTER_COLUMNS: readonly EncounterColumnKey[] = [
  "matchup",
  "tournament",
  "score",
  "format",
  "closeness",
  "stage",
  "maps",
  "state",
  "when",
  "logs"
];

// Message keys are kept as literal unions so the strictly-typed `t()` accepts a
// table lookup directly.
type StateLabelKey =
  | "encounters.state.live"
  | "encounters.state.upcoming"
  | "encounters.state.final"
  | "encounters.state.pending"
  | "encounters.state.open";

const STATE_LABEL_KEY: Record<EncounterState, StateLabelKey> = {
  Live: "encounters.state.live",
  Upcoming: "encounters.state.upcoming",
  Final: "encounters.state.final",
  Pending: "encounters.state.pending",
  Open: "encounters.state.open"
};

const STATE_PILL_VARIANT: Record<EncounterState, TournamentStatusVariant> = {
  Live: "live",
  Upcoming: "upcoming",
  Final: "finished",
  Pending: "upcoming",
  Open: "open"
};

type ColumnHeaderKey =
  | "encounters.col.matchup"
  | "common.tournament"
  | "encounters.col.score"
  | "encounters.col.format"
  | "encounters.col.closeness"
  | "common.stage"
  | "encounters.col.maps"
  | "common.status"
  | "encounters.col.when"
  | "encounters.col.logs";

const HEADER: Record<EncounterColumnKey, { key: ColumnHeaderKey; align?: "r" | "c" }> = {
  matchup: { key: "encounters.col.matchup" },
  tournament: { key: "common.tournament" },
  score: { key: "encounters.col.score", align: "r" },
  format: { key: "encounters.col.format", align: "c" },
  closeness: { key: "encounters.col.closeness" },
  stage: { key: "common.stage" },
  maps: { key: "encounters.col.maps", align: "c" },
  state: { key: "common.status", align: "c" },
  when: { key: "encounters.col.when", align: "r" },
  logs: { key: "encounters.col.logs", align: "c" }
};

/**
 * An upset is a completed series that was decided by a single map yet scored as
 * very close — worth surfacing over the plain "Final" label.
 */
function isUpset(encounter: Encounter): boolean {
  return (
    getEncounterWinner(encounter) != null &&
    encounter.closeness != null &&
    encounter.closeness >= 0.8 &&
    Math.abs(encounter.score.home - encounter.score.away) === 1
  );
}

export function useEncountersTableController({
  data,
  initialPage,
  search,
  tournamentId,
  workspaceId,
  enabled = true
}: {
  data?: PaginatedResponse<Encounter>;
  initialPage: number;
  search: string;
  tournamentId: number;
  workspaceId?: number | null;
  enabled?: boolean;
}) {
  const pathname = usePathname();
  const [querySearch, setQuerySearch] = useState(search);
  const [currentPage, setCurrentPage] = useState(initialPage);
  const previousUrlStateRef = useRef({ page: initialPage, search });
  const searchInputRef = useRef<HTMLInputElement>(null);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const encountersQuery = useQuery({
    queryKey: tournamentQueryKeys.encountersPage(
      tournamentId,
      workspaceId,
      currentPage,
      querySearch
    ),
    queryFn: () =>
      encounterService.getAll(
        currentPage,
        querySearch,
        tournamentId,
        PER_PAGE,
        undefined,
        undefined,
        workspaceId
      ),
    enabled,
    placeholderData: (previousData) => previousData,
    initialData: data && currentPage === initialPage && querySearch === search ? data : undefined
  });

  useEffect(() => {
    const handlePopState = () => {
      const params = new URLSearchParams(window.location.search);
      const nextPage = Number.parseInt(params.get("page") ?? "1", 10) || 1;
      const nextSearch = params.get("search") ?? "";
      clearTimeout(searchTimerRef.current ?? undefined);
      previousUrlStateRef.current = { page: nextPage, search: nextSearch };
      setQuerySearch(nextSearch);
      setCurrentPage(nextPage);
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(
    () => () => {
      clearTimeout(searchTimerRef.current ?? undefined);
    },
    []
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const currentSearch = params.get("search") ?? "";
    const currentPageParam = Number.parseInt(params.get("page") ?? "1", 10) || 1;
    const previousUrlState = previousUrlStateRef.current;
    const searchChanged = previousUrlState.search !== querySearch;
    const pageChanged = previousUrlState.page !== currentPage;

    if (!searchChanged && !pageChanged) return;
    if (currentSearch === querySearch && currentPageParam === currentPage) {
      previousUrlStateRef.current = { page: currentPage, search: querySearch };
      return;
    }

    if (querySearch) params.set("search", querySearch);
    else params.delete("search");
    if (currentPage > 1) params.set("page", String(currentPage));
    else params.delete("page");

    const query = params.toString();
    const nextUrl = query ? `${pathname}?${query}` : pathname;
    if (searchChanged) window.history.replaceState(null, "", nextUrl);
    else window.history.pushState(null, "", nextUrl);
    previousUrlStateRef.current = { page: currentPage, search: querySearch };
  }, [currentPage, pathname, querySearch]);

  const onSearchInput = (nextSearch: string) => {
    clearTimeout(searchTimerRef.current ?? undefined);
    searchTimerRef.current = setTimeout(() => {
      setQuerySearch(nextSearch);
      setCurrentPage(1);
    }, 300);
  };

  return {
    encountersQuery,
    currentPage,
    setCurrentPage,
    searchInputRef,
    onSearchInput
  };
}

/**
 * Card + scroll container + table. Search and pagination are the caller's, so
 * the standalone `/encounters` page can place its own filter bar, error state
 * and `DataPagination` around exactly this table.
 */
export function EncountersDataTable({
  rows,
  columns = DEFAULT_ENCOUNTER_COLUMNS,
  loading = false,
  className
}: Readonly<{
  rows: Encounter[];
  columns?: readonly EncounterColumnKey[];
  /** Renders placeholder rows instead of collapsing the table to a single line. */
  loading?: boolean;
  className?: string;
}>) {
  const router = useRouter();
  const t = useTranslations();
  const format = useFormatter();
  // Relative time ("3h ago") must only be produced after hydration: the server
  // renders at one instant and the client at another, which is a hydration
  // mismatch. `useSyncExternalStore` reads "am I hydrated" as the external fact
  // it is, instead of cascading a render with setState inside an effect.
  const isHydrated = useSyncExternalStore(subscribeNoop, () => true, () => false);
  const now = isHydrated ? new Date() : null;

  const isWide = columns.length > DEFAULT_ENCOUNTER_COLUMNS.length;

  const whenParts = (encounter: Encounter) => {
    if (isEncounterLive(encounter)) {
      return { day: t("common.now"), time: t("encounters.state.live"), live: true };
    }
    const source =
      encounter.ended_at ?? encounter.started_at ?? encounter.scheduled_at ?? encounter.created_at;
    if (!source) return { day: t("common.tbd"), time: "", live: false };
    const date = new Date(source);
    if (Number.isNaN(date.getTime())) return { day: t("common.tbd"), time: "", live: false };
    return {
      day: format.dateTime(date, { month: "short", day: "numeric" }),
      time: now ? format.relativeTime(date, now) : format.dateTime(date, { timeStyle: "short" }),
      live: false
    };
  };

  const renderCell = (column: EncounterColumnKey, encounter: Encounter) => {
    const winner = getEncounterWinner(encounter);

    switch (column) {
      case "matchup":
        return (
          <td key={column}>
            <div className="m-up">
              <div className={cn("row", winner === "home" && "winner", winner === "away" && "loser")}>
                <TeamName
                  team={encounter.home_team}
                  fallback={t("common.tbd")}
                  size="xs"
                  nameClassName="nm"
                />
              </div>
              <div className={cn("row", winner === "away" && "winner", winner === "home" && "loser")}>
                <TeamName
                  team={encounter.away_team}
                  fallback={t("common.tbd")}
                  size="xs"
                  nameClassName="nm"
                />
              </div>
            </div>
          </td>
        );

      case "tournament":
        return (
          <td key={column}>
            <span className="m-round">{encounter.tournament?.name ?? "—"}</span>
          </td>
        );

      case "score":
        return (
          <td key={column} className="r">
            <div className="m-score">
              <span className={winner === "home" ? "w" : "l"}>{encounter.score.home}</span>
              <span className="sep">–</span>
              <span className={winner === "away" ? "w" : "l"}>{encounter.score.away}</span>
            </div>
          </td>
        );

      case "format":
        return (
          <td
            key={column}
            className="c aqt-tnum text-caption tabular-nums text-[color:var(--aqt-fg-dim)]"
          >
            {t("encounters.bestOfShort", { count: encounter.best_of })}
          </td>
        );

      case "closeness": {
        const closeness = encounter.closeness;
        return (
          <td key={column}>
            {closeness == null ? (
              <span className="num text-[color:var(--aqt-fg-faint)]">—</span>
            ) : (
              <div className="m-close">
                <span className="track">
                  <span
                    className={cn("fill", closeness >= 0.8 && "hot")}
                    style={{ width: `${Math.round(closeness * 100)}%` }}
                  />
                </span>
                <span className="num tabular-nums">{Math.round(closeness * 100)}%</span>
              </div>
            )}
          </td>
        );
      }

      case "stage":
        return (
          <td key={column}>
            <span className="m-round">
              {encounter.stage_item?.name ??
                encounter.stage?.name ??
                t("common.unassignedStage")}
              <span className="stage"> · {t("encounters.roundShort", { round: encounter.round })}</span>
            </span>
          </td>
        );

      case "maps": {
        const played = [...(encounter.matches ?? [])].sort((a, b) => a.id - b.id);
        return (
          <td key={column} className="c">
            {played.length ? (
              <span
                role="img"
                className={styles.pips}
                aria-label={t("encounters.mapsCount", { count: played.length })}
              >
                {played.map((match) => (
                  <span
                    key={match.id}
                    aria-hidden
                    className={cn(
                      styles.pip,
                      match.score.home > match.score.away ? styles.pipHome : styles.pipAway
                    )}
                  />
                ))}
              </span>
            ) : (
              <span className="num text-[color:var(--aqt-fg-faint)]">—</span>
            )}
          </td>
        );
      }

      case "state": {
        const state = getEncounterState(encounter);
        const upset = state === "Final" && isUpset(encounter);
        return (
          <td key={column} className="c">
            <TournamentStatusPill
              status={upset ? "upset" : STATE_PILL_VARIANT[state]}
              className="px-[7px] py-0.5"
            >
              {upset ? t("encounters.state.upset") : t(STATE_LABEL_KEY[state])}
            </TournamentStatusPill>
          </td>
        );
      }

      case "when": {
        const when = whenParts(encounter);
        return (
          <td key={column} className="r">
            <div className="m-when items-end">
              <span className="day">{when.day}</span>
              <span className={cn("time tabular-nums", when.live && "live")}>
                {when.live ? (
                  <StatusDot className="mr-1 size-[7px] text-[color:var(--aqt-status-live)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--aqt-status-live)_18%,transparent)] [animation:aqtPulse_2s_ease-in-out_infinite] motion-reduce:animate-none" />
                ) : null}
                {when.time}
              </span>
            </div>
          </td>
        );
      }

      case "logs":
        return (
          <td key={column} className="c">
            {/* Layout box and click shield, not a control: the whole row
                navigates, so a click landing on the badge must not. There is
                deliberately no keyboard twin — this only ever catches clicks on
                the indicator's non-focusable `<span>` variants. Its focusable
                variants stop propagation themselves, and the row's key handler
                already ignores events whose target is not the row. */}
            <div
              role="presentation"
              className="m-media justify-center"
              onClick={(event) => event.stopPropagation()}
            >
              <MatchLogIndicator
                hasLogs={encounter.has_logs}
                logs={
                  encounter.has_logs
                    ? (encounter.matches ?? []).map((match, index) => ({
                        matchId: match.id,
                        label: match.map?.name ?? `${index + 1}`
                      }))
                    : undefined
                }
              />
            </div>
          </td>
        );
    }
  };

  return (
    // `.matches-card` / `.m-scroll` / `table.m` are all scoped as DESCENDANTS of
    // `.aqt-matches` in `EncountersTable.css`, so the scope class must sit on an
    // ancestor element — not on the card itself.
    <div className={cn("aqt-matches min-w-0", className)}>
      <div className="matches-card min-w-0">
        <section
          className={cn("m-scroll", styles.tableViewport)}
          aria-label={t("tournamentDetail.publicPages.matches.tableLabel")}
          tabIndex={0}
        >
          <table className={cn("m", styles.matchesTable, isWide && styles.matchesTableWide)}>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column} scope="col" className={HEADER[column].align}>
                    {t(HEADER[column].key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading
                ? Array.from({ length: SKELETON_ROWS }).map((_, index) => (
                    <tr key={`skeleton-${index}`}>
                      {columns.map((column) => (
                        <td key={column}>
                          <Skeleton className="h-6 w-full rounded-md" />
                        </td>
                      ))}
                    </tr>
                  ))
                : rows.map((encounter) => {
                    const openEncounter = () => router.push(`/encounters/${encounter.id}`);

                    return (
                      <tr
                        key={encounter.id}
                        className={cn(isEncounterLive(encounter) && "live")}
                        tabIndex={0}
                        onClick={openEncounter}
                        onKeyDown={(event) => {
                          activateEncounterRowFromKeyboard(event, openEncounter);
                        }}
                      >
                        {columns.map((column) => renderCell(column, encounter))}
                      </tr>
                    );
                  })}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}

const EncountersTable = ({
  encounters,
  currentPage,
  onSetPage,
  search,
  searchInputRef,
  onSearchInput,
  hideTournament = false
}: {
  encounters: PaginatedResponse<Encounter>;
  currentPage: number;
  onSetPage: (page: number) => void;
  search: string;
  searchInputRef: React.RefObject<HTMLInputElement | null>;
  onSearchInput: (nextSearch: string) => void;
  hideTournament?: boolean;
}) => {
  const t = useTranslations();
  const [searchValue, setSearchValue] = useState(search);
  const columns = hideTournament
    ? DEFAULT_ENCOUNTER_COLUMNS.filter((column) => column !== "tournament")
    : DEFAULT_ENCOUNTER_COLUMNS;
  const totalPages = Math.max(1, Math.ceil((encounters.total ?? 0) / PER_PAGE));

  // The controller rewrites the query string, so a back navigation has to put
  // the field back in step with the URL it just restored.
  useEffect(() => {
    const syncFromUrl = () =>
      setSearchValue(new URLSearchParams(window.location.search).get("search") ?? "");
    window.addEventListener("popstate", syncFromUrl);
    return () => window.removeEventListener("popstate", syncFromUrl);
  }, []);

  return (
    <div className="aqt-matches flex min-w-0 flex-col gap-4">
      <SearchField
        ref={searchInputRef}
        value={searchValue}
        onValueChange={(next) => {
          setSearchValue(next);
          onSearchInput(next);
        }}
        label={t("tournamentDetail.publicPages.matches.searchLabel")}
        placeholder={t("tournamentDetail.publicPages.matches.searchPlaceholder")}
        containerClassName="w-[300px] max-w-full"
      />

      <EncountersDataTable rows={encounters.results ?? []} columns={columns} />

      <DataPagination page={currentPage} totalPages={totalPages} onPageChange={onSetPage} />
    </div>
  );
};

export default EncountersTable;
