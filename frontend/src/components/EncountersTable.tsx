"use client";

import React, { useEffect, useRef, useState } from "react";
import { Encounter } from "@/types/encounter.types";
import { Search } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useDebounce } from "use-debounce";
import { useQuery } from "@tanstack/react-query";

import { PaginationControlled } from "@/components/ui/pagination-with-links";
import { PaginatedResponse } from "@/types/pagination.types";
import { cn } from "@/lib/utils";
import encounterService from "@/services/encounter.service";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";

const COMPLETED_STATUSES = new Set(["completed", "finished", "closed"]);
const PER_PAGE = 15;


const getStageLabel = (encounter: Encounter) =>
  encounter.stage_item?.name ?? encounter.stage?.name ?? "Unassigned";

function getMatchMeta(encounter: Encounter) {
  const isCompleted = COMPLETED_STATUSES.has(encounter.status);
  const isLive = !isCompleted && Boolean(encounter.started_at) && !encounter.ended_at;
  let winner: "home" | "away" | null = null;
  if (isCompleted && encounter.score.home !== encounter.score.away) {
    winner = encounter.score.home > encounter.score.away ? "home" : "away";
  }
  return { isCompleted, isLive, winner };
}

function formatAgo(value: Date | string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const minutes = Math.round((Date.now() - date.getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
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
    live: false,
  };
}

const EncountersTable = ({
  data,
  InitialPage,
  search,
  hideTournament,
  tournamentId = null,
  workspaceId = null,
}: {
  data?: PaginatedResponse<Encounter>;
  InitialPage: number;
  search: string;
  hideTournament?: boolean;
  tournamentId?: number | null;
  workspaceId?: number | null;
}) => {
  const router = useRouter();
  const pathname = usePathname();
  const [searchValue, setSearchValue] = useState<string>(search);
  const [debouncedSearchValue] = useDebounce(searchValue, 300);
  const [currentPage, setCurrentPage] = useState<number>(InitialPage);
  const previousDebouncedSearchRef = useRef(search);
  const previousUrlStateRef = useRef({ page: InitialPage, search });

  useEffect(() => {
    setSearchValue(search);
  }, [search]);

  useEffect(() => {
    if (previousDebouncedSearchRef.current !== debouncedSearchValue) {
      previousDebouncedSearchRef.current = debouncedSearchValue;
      setCurrentPage(1);
    }
  }, [debouncedSearchValue]);

  const encountersQuery = useQuery({
    queryKey:
      tournamentId != null
        ? tournamentQueryKeys.encountersPage(
            tournamentId,
            workspaceId,
            currentPage,
            debouncedSearchValue,
          )
        : (["encounters", currentPage, debouncedSearchValue] as const),
    queryFn: () =>
      encounterService.getAll(
        currentPage,
        debouncedSearchValue,
        tournamentId,
        PER_PAGE,
        undefined,
        undefined,
        workspaceId,
      ),
    placeholderData: (previousData) => previousData,
    initialData:
      data && currentPage === InitialPage && debouncedSearchValue === search
        ? data
        : undefined,
  });

  const encounters = encountersQuery.data ?? data ?? {
    page: currentPage,
    per_page: PER_PAGE,
    total: 0,
    results: [],
  };

  useEffect(() => {
    const handlePopState = () => {
      const params = new URLSearchParams(window.location.search);
      const nextPage = Number.parseInt(params.get("page") ?? "1", 10) || 1;
      previousUrlStateRef.current = { page: nextPage, search: debouncedSearchValue };
      setCurrentPage(nextPage);
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [debouncedSearchValue]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const currentSearch = params.get("search") ?? "";
    const currentPageParam = Number.parseInt(params.get("page") ?? "1", 10) || 1;

    const previousUrlState = previousUrlStateRef.current;
    const searchChanged = previousUrlState.search !== debouncedSearchValue;
    const pageChanged = previousUrlState.page !== currentPage;

    if (!searchChanged && !pageChanged) return;

    if (currentSearch === debouncedSearchValue && currentPageParam === currentPage) {
      previousUrlStateRef.current = { page: currentPage, search: debouncedSearchValue };
      return;
    }

    if (debouncedSearchValue) params.set("search", debouncedSearchValue);
    else params.delete("search");

    if (currentPage > 1) params.set("page", String(currentPage));
    else params.delete("page");

    const query = params.toString();
    const nextUrl = query ? `${pathname}?${query}` : pathname;

    if (searchChanged) window.history.replaceState(null, "", nextUrl);
    else window.history.pushState(null, "", nextUrl);

    previousUrlStateRef.current = { page: currentPage, search: debouncedSearchValue };
  }, [currentPage, debouncedSearchValue, pathname]);

  const rows = encounters.results ?? [];
  const columnCount = hideTournament ? 7 : 8;

  return (
    <div className="aqt-matches flex flex-col gap-4">
      <div className="m-search">
        <Search width={14} height={14} />
        <input
          placeholder="Search by name"
          value={searchValue}
          onChange={(event) => setSearchValue(event.target.value)}
        />
      </div>

      <div className="matches-card">
        <div className="m-scroll">
          <table className="m">
            <thead>
              <tr>
                <th>Matchup</th>
                {!hideTournament && <th>Tournament</th>}
                <th className="r">Score</th>
                <th className="c">Format</th>
                <th>Closeness</th>
                <th>Stage</th>
                <th className="r">When</th>
                <th className="c">Logs</th>
              </tr>
            </thead>
            <tbody>
              {encountersQuery.isLoading ? (
                <tr>
                  <td colSpan={columnCount} className="m-empty">
                    Loading matches…
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={columnCount} className="m-empty">
                    No matches found.
                  </td>
                </tr>
              ) : (
                rows.map((encounter) => {
                  const meta = getMatchMeta(encounter);
                  const when = formatWhen(encounter, meta.isLive);
                  const closeness = encounter.closeness;
                  const tournamentName = encounter.tournament?.is_league
                    ? encounter.tournament.name
                    : `Tournament ${encounter.tournament?.number ?? "—"}`;

                  return (
                    <tr
                      key={encounter.id}
                      className={cn(meta.isLive && "live")}
                      onClick={() => router.push(`/encounters/${encounter.id}`)}
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

                      <td className="c font-mono text-[var(--fg-dim)] text-[13px]">
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
                          onClick={(e) => e.stopPropagation()}
                        >
                          <MatchLogIndicator
                            hasLogs={encounter.has_logs}
                            logs={
                              encounter.has_logs
                                ? (encounter.matches ?? []).map((m, i) => ({
                                    matchId: m.id,
                                    label: m.map?.name ?? `Map ${i + 1}`
                                  }))
                                : undefined
                            }
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="m-pagination">
        <PaginationControlled
          page={currentPage}
          totalCount={encounters.total ?? 0}
          pageSize={PER_PAGE}
          onSetPage={setCurrentPage}
        />
      </div>
    </div>
  );
};

export default EncountersTable;
