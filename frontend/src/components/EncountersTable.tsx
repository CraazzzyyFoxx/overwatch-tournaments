"use client";

import React, { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import styles from "@/app/(site)/tournaments/[id]/TournamentDetail.module.css";
import {
  getPublicPageQueryPresentation,
  type PublicPageQueryState
} from "@/app/(site)/tournaments/[id]/pages/publicPageQueryPresentation";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import { PaginationControlled } from "@/components/ui/pagination-with-links";
import { cn } from "@/lib/utils";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import encounterService from "@/services/encounter.service";
import { Encounter } from "@/types/encounter.types";
import { PaginatedResponse } from "@/types/pagination.types";

const COMPLETED_STATUSES = new Set(["completed", "finished", "closed"]);
const PER_PAGE = 15;

export const getEncountersQueryPresentation = (state: PublicPageQueryState) =>
  getPublicPageQueryPresentation(state);

const getStageLabel = (encounter: Encounter) =>
  encounter.stage_item?.name ?? encounter.stage?.name ?? "Unassigned";

function getMatchMeta(encounter: Encounter) {
  const isCompleted = COMPLETED_STATUSES.has(encounter.status);
  const isLive = !isCompleted && Boolean(encounter.started_at) && !encounter.ended_at;
  let winner: "home" | "away" | null = null;
  if (isCompleted && encounter.score.home !== encounter.score.away) {
    winner = encounter.score.home > encounter.score.away ? "home" : "away";
  }
  return { isLive, winner };
}

function formatAgo(value: Date | string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const minutes = Math.round((Date.now() - date.getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function formatWhen(encounter: Encounter, isLive: boolean) {
  if (isLive) return { day: "Now", time: "Live", live: true };
  const source =
    encounter.ended_at ?? encounter.started_at ?? encounter.scheduled_at ?? encounter.created_at;
  if (!source) return { day: "TBD", time: "", live: false };
  const date = new Date(source);
  return {
    day: date.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    time: formatAgo(source),
    live: false
  };
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
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
      previousUrlStateRef.current = { page: nextPage, search: nextSearch };
      if (searchInputRef.current) searchInputRef.current.value = nextSearch;
      setQuerySearch(nextSearch);
      setCurrentPage(nextPage);
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(
    () => () => {
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
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

  const onSearchInput = (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextSearch = event.target.value;
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
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
  onSearchInput: (event: React.ChangeEvent<HTMLInputElement>) => void;
  hideTournament?: boolean;
}) => {
  const router = useRouter();
  const t = useTranslations();
  const rows = encounters.results ?? [];

  return (
    <div className="aqt-matches flex min-w-0 flex-col gap-4">
      <div className="m-search">
        <Search width={14} height={14} aria-hidden="true" />
        <input
          ref={searchInputRef}
          type="search"
          aria-label={t("tournamentDetail.publicPages.matches.searchLabel")}
          placeholder={t("tournamentDetail.publicPages.matches.searchPlaceholder")}
          defaultValue={search}
          onChange={onSearchInput}
        />
      </div>

      <div className="matches-card min-w-0">
        <div
          className={cn("m-scroll", styles.tableViewport)}
          role="region"
          aria-label={t("tournamentDetail.publicPages.matches.tableLabel")}
          tabIndex={0}
        >
          <table className={cn("m", styles.matchesTable)}>
            <thead>
              <tr>
                <th scope="col">Matchup</th>
                {!hideTournament && <th scope="col">Tournament</th>}
                <th scope="col" className="r">
                  Score
                </th>
                <th scope="col" className="c">
                  Format
                </th>
                <th scope="col">Closeness</th>
                <th scope="col">Stage</th>
                <th scope="col" className="r">
                  When
                </th>
                <th scope="col" className="c">
                  Logs
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((encounter) => {
                const meta = getMatchMeta(encounter);
                const when = formatWhen(encounter, meta.isLive);
                const closeness = encounter.closeness;
                const tournamentName = encounter.tournament?.is_league
                  ? encounter.tournament.name
                  : `Tournament ${encounter.tournament?.number ?? "—"}`;
                const openEncounter = () => router.push(`/encounters/${encounter.id}`);

                return (
                  <tr
                    key={encounter.id}
                    className={cn(meta.isLive && "live")}
                    tabIndex={0}
                    onClick={openEncounter}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") openEncounter();
                    }}
                  >
                    <td>
                      <div className="m-up">
                        <div
                          className={cn(
                            "row",
                            meta.winner === "home" && "winner",
                            meta.winner === "away" && "loser"
                          )}
                        >
                          <span className="nm">{encounter.home_team?.name ?? "TBD"}</span>
                        </div>
                        <div
                          className={cn(
                            "row",
                            meta.winner === "away" && "winner",
                            meta.winner === "home" && "loser"
                          )}
                        >
                          <span className="nm">{encounter.away_team?.name ?? "TBD"}</span>
                        </div>
                      </div>
                    </td>

                    {!hideTournament && (
                      <td>
                        <span className="m-round">{tournamentName}</span>
                      </td>
                    )}

                    <td className="r">
                      <div className="m-score">
                        <span className={meta.winner === "home" ? "w" : "l"}>
                          {encounter.score.home}
                        </span>
                        <span className="sep">–</span>
                        <span className={meta.winner === "away" ? "w" : "l"}>
                          {encounter.score.away}
                        </span>
                      </div>
                    </td>
                    <td className="c font-mono text-[13px] text-[var(--fg-dim)]">
                      Bo{encounter.best_of}
                    </td>
                    <td>
                      {closeness != null ? (
                        <div className="m-close">
                          <span className="track">
                            <span
                              className={cn("fill", closeness >= 0.8 && "hot")}
                              style={{ width: `${Math.round(closeness * 100)}%` }}
                            />
                          </span>
                          <span className="num">{Math.round(closeness * 100)}%</span>
                        </div>
                      ) : (
                        <span className="num" style={{ color: "var(--fg-faint)" }}>
                          —
                        </span>
                      )}
                    </td>
                    <td>
                      <span className="m-round">
                        {getStageLabel(encounter)}
                        <span className="stage"> · R{encounter.round}</span>
                      </span>
                    </td>
                    <td className="r">
                      <div className="m-when" style={{ alignItems: "flex-end" }}>
                        <span className="day">{when.day}</span>
                        <span className={cn("time", when.live && "live")}>
                          {when.live && <span className="m-live-dot" style={{ marginRight: 4 }} />}
                          {when.time}
                        </span>
                      </div>
                    </td>
                    <td className="c">
                      <div
                        className="m-media"
                        style={{ justifyContent: "center" }}
                        onClick={(event) => event.stopPropagation()}
                      >
                        <MatchLogIndicator
                          hasLogs={encounter.has_logs}
                          logs={
                            encounter.has_logs
                              ? (encounter.matches ?? []).map((match, index) => ({
                                  matchId: match.id,
                                  label: match.map?.name ?? `Map ${index + 1}`
                                }))
                              : undefined
                          }
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="m-pagination">
        <PaginationControlled
          page={currentPage}
          totalCount={encounters.total ?? 0}
          pageSize={PER_PAGE}
          onSetPage={onSetPage}
        />
      </div>
    </div>
  );
};

export default EncountersTable;
