"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useDebounce } from "use-debounce";
import { EncounterWithUserStats } from "@/types/user.types";
import { DataPagination } from "@/components/ui/data-pagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useQueryParams } from "@/hooks/useQueryParams";
import { CardSurface } from "@/components/profile/atoms";
import MatchRow from "@/app/(site)/users/components/matches/MatchRow";
import MatchesFilterBar, { type Filter } from "@/app/(site)/users/components/matches/MatchesFilterBar";
import MatchesSidebars, {
  type OpponentStat,
  type StageStats
} from "@/app/(site)/users/components/matches/MatchesSidebars";

interface Props {
  encounters: EncounterWithUserStats[];
  total: number;
  page: number;
  perPage: number;
  selfUserId: number;
  /** Aggregated server-side over ALL the user's encounters (Matches sidebars). */
  opponents: OpponentStat[];
  stages: StageStats;
  /** "All games": rows mark their game and the game-bound MVP filter is not offered. */
  allGames?: boolean;
  /** Above the sidebars: the per-game tabs of the (game-bound) matches summary under "all games". */
  sidebarTabs?: ReactNode;
}

/** Server-side Matches-tab filters (mirrors the encounters endpoint params). */
export interface MatchesFilters {
  result?: "win" | "loss" | "draw";
  stage?: "group" | "playoffs" | "finals";
  mvp1?: boolean;
  hasLogs?: boolean;
  opponent?: string;
}

const MatchesTable = ({
  encounters,
  total,
  page,
  perPage,
  selfUserId,
  opponents,
  stages,
  allGames = false,
  sidebarTabs
}: Props) => {
  const { searchParams, setParams } = useQueryParams({ mode: "replace", resetOnChange: ["page"] });
  const t = useTranslations();
  const headers = [
    t("users.matches.colTournament"),
    t("users.matches.colStage"),
    t("users.matches.colMatch"),
    t("users.matches.colScore"),
    t("common.characters"),
    t("users.matches.colMvp"),
    t("users.matches.colCloseness"),
    t("users.matches.colLogs")
  ];
  // Filters live in the URL and are applied server-side (the page refetches),
  // so they work across all pages — not just the current one.
  const urlOpp = searchParams?.get("mOpp") ?? "";
  const [search, setSearch] = useState(urlOpp);
  const [debouncedSearch] = useDebounce(search, 400);

  const activeFilter: Filter = (() => {
    const r = searchParams?.get("mResult");
    if (r === "win") return "wins";
    if (r === "loss") return "losses";
    if (r === "draw") return "draws";
    const s = searchParams?.get("mStage");
    if (s === "group") return "group";
    if (s === "playoffs") return "playoffs";
    if (s === "finals") return "finals";
    if (searchParams?.get("mMvp1") === "1") return "mvp1";
    if (searchParams?.get("mLogs") === "1") return "has_logs";
    return "all";
  })();

  // `setParams` clears `page` whenever a filter changes, so narrowing never
  // strands the user on a page that no longer exists.
  const applyFilter = (key: Filter) => {
    setParams({
      mResult: key === "wins" ? "win" : key === "losses" ? "loss" : key === "draws" ? "draw" : null,
      mStage: key === "group" || key === "playoffs" || key === "finals" ? key : null,
      mMvp1: key === "mvp1" ? "1" : null,
      mLogs: key === "has_logs" ? "1" : null
    });
  };

  // Push the debounced opponent search to the URL (server-side filter).
  useEffect(() => {
    const value = debouncedSearch.trim();
    if (value === urlOpp) return;
    setParams({ mOpp: value || null });
  }, [debouncedSearch]);

  const pages = Math.max(1, Math.ceil(total / perPage));

  const handlePageChange = (newPage: number) => setParams({ page: newPage });

  // `opponents` and `stages` are computed on the backend over all the user's
  // encounters (see UserEncountersPage / users/{id}/matches/summary).

  return (
    <div className="aqt-player">
      <MatchesFilterBar
        activeFilter={activeFilter}
        onApplyFilter={applyFilter}
        search={search}
        onSearchChange={setSearch}
        allGames={allGames}
      />

      <div className="grid grid-cols-1 items-start gap-3.5 xl:grid-cols-[1fr_320px]">
        <CardSurface flush>
          <Table className="aqt-tnum border-collapse text-body">
            <TableHeader>
              <TableRow>
                {headers.map((h) => (
                  <TableHead key={h} className="aqt-tnum bg-[color:var(--aqt-overlay-1)] px-3.5 py-3">
                    {h}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {encounters.map((enc) => (
                <MatchRow key={enc.id} enc={enc} selfUserId={selfUserId} showGame={allGames} />
              ))}
              {encounters.length === 0 ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={8} className="px-3.5 py-10 text-center text-[color:var(--aqt-fg-dim)]">
                    {t("users.matches.noMatches")}
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
          <DataPagination
            page={page}
            totalPages={pages}
            onPageChange={handlePageChange}
            className="border-t border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-[18px] py-3.5"
            leading={
              <span className="aqt-tnum text-caption text-[color:var(--aqt-fg-dim)]">
                {t("common.showingRange", {
                  start: String((page - 1) * perPage + 1),
                  end: String((page - 1) * perPage + encounters.length),
                  total: String(total)
                })}
              </span>
            }
          />
        </CardSurface>

        {/* Stretched to the row so the sidebars stay sticky inside it. */}
        <div className="flex min-w-0 flex-col self-stretch">
          {sidebarTabs}
          <MatchesSidebars opponentStats={opponents} stageStats={stages} />
        </div>
      </div>
    </div>
  );
};

export default MatchesTable;
