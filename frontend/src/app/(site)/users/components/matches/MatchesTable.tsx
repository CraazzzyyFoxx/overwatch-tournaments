"use client";

import React, { useEffect, useState } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useDebounce } from "use-debounce";
import { cn } from "@/lib/utils";
import { EncounterWithUserStats } from "@/types/user.types";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
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
}

/** Server-side Matches-tab filters (mirrors the encounters endpoint params). */
export interface MatchesFilters {
  result?: "win" | "loss" | "draw";
  stage?: "group" | "playoffs" | "finals";
  mvp1?: boolean;
  hasLogs?: boolean;
  opponent?: string;
}

const MatchesTable = ({ encounters, total, page, perPage, selfUserId, opponents, stages }: Props) => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  // Filters live in the URL and are applied server-side (the page refetches),
  // so they work across all pages — not just the current one.
  const urlOpp = searchParams.get("mOpp") ?? "";
  const [search, setSearch] = useState(urlOpp);
  const [debouncedSearch] = useDebounce(search, 400);

  const activeFilter: Filter = (() => {
    const r = searchParams.get("mResult");
    if (r === "win") return "wins";
    if (r === "loss") return "losses";
    if (r === "draw") return "draws";
    const s = searchParams.get("mStage");
    if (s === "group") return "group";
    if (s === "playoffs") return "playoffs";
    if (s === "finals") return "finals";
    if (searchParams.get("mMvp1") === "1") return "mvp1";
    if (searchParams.get("mLogs") === "1") return "has_logs";
    return "all";
  })();

  const pushParams = (mutate: (p: URLSearchParams) => void) => {
    const params = new URLSearchParams(searchParams?.toString());
    mutate(params);
    params.set("page", "1");
    router.push(`${pathname}?${params.toString()}`);
  };

  const applyFilter = (key: Filter) => {
    pushParams((p) => {
      p.delete("mResult");
      p.delete("mStage");
      p.delete("mMvp1");
      p.delete("mLogs");
      if (key === "wins") p.set("mResult", "win");
      else if (key === "losses") p.set("mResult", "loss");
      else if (key === "draws") p.set("mResult", "draw");
      else if (key === "group") p.set("mStage", "group");
      else if (key === "playoffs") p.set("mStage", "playoffs");
      else if (key === "finals") p.set("mStage", "finals");
      else if (key === "mvp1") p.set("mMvp1", "1");
      else if (key === "has_logs") p.set("mLogs", "1");
    });
  };

  // Push the debounced opponent search to the URL (server-side filter).
  useEffect(() => {
    if (debouncedSearch.trim() === urlOpp) return;
    pushParams((p) => {
      const v = debouncedSearch.trim();
      if (v) p.set("mOpp", v);
      else p.delete("mOpp");
    });
  }, [debouncedSearch]);

  const pages = Math.max(1, Math.ceil(total / perPage));

  const handlePageChange = (newPage: number) => {
    const params = new URLSearchParams(searchParams || undefined);
    params.set("page", String(newPage));
    router.push(`${pathname}?${params.toString()}`);
  };

  // `opponents` and `stages` are computed on the backend over all the user's
  // encounters (see UserEncountersPage / users/{id}/matches/summary).

  return (
    <div className="aqt-player">
      <MatchesFilterBar
        activeFilter={activeFilter}
        onApplyFilter={applyFilter}
        search={search}
        onSearchChange={setSearch}
      />

      <div className="grid grid-cols-1 items-start gap-3.5 xl:grid-cols-[1fr_320px]">
        <CardSurface flush>
          <div className="overflow-x-auto">
            <table className="aqt-tnum w-full border-collapse text-[14px]">
              <thead>
                <tr>
                  {["Tournament", "Stage", "Match", "Score", "Heroes", "MVP", "Close.", "Logs"].map((h) => (
                    <th
                      key={h}
                      className="aqt-mono border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.015)] px-3.5 py-3 text-left text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {encounters.map((enc) => (
                  <MatchRow key={enc.id} enc={enc} selfUserId={selfUserId} />
                ))}
                {encounters.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-3.5 py-10 text-center text-[color:var(--aqt-fg-dim)]">
                      No matches for current filter
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.012)] px-[18px] py-3.5">
            <span className="aqt-mono text-[13px] text-[color:var(--aqt-fg-dim)]">
              Showing {(page - 1) * perPage + 1}–{(page - 1) * perPage + encounters.length} of {total}
            </span>
            <div className="flex gap-1">
              <PageBtn disabled={page <= 1} onClick={() => handlePageChange(page - 1)}>‹</PageBtn>
              {Array.from({ length: Math.min(3, pages) }, (_, i) => i + 1).map((n) => (
                <PageBtn key={n} active={n === page} onClick={() => handlePageChange(n)}>{n}</PageBtn>
              ))}
              {pages > 3 ? (
                <>
                  {page > 4 ? <span className="aqt-mono px-2 text-[color:var(--aqt-fg-faint)]">…</span> : null}
                  <PageBtn active={page === pages} onClick={() => handlePageChange(pages)}>{pages}</PageBtn>
                </>
              ) : null}
              <PageBtn disabled={page >= pages} onClick={() => handlePageChange(page + 1)}>›</PageBtn>
            </div>
          </div>
        </CardSurface>

        <MatchesSidebars opponentStats={opponents} stageStats={stages} />
      </div>
    </div>
  );
};

interface PageBtnProps {
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}

const PageBtn = ({ active, disabled, onClick, children }: PageBtnProps) => (
  <button
    onClick={onClick}
    disabled={disabled}
    className={cn(
      "aqt-mono inline-flex h-8 min-w-[32px] items-center justify-center rounded-[6px] border px-2 text-[13px] transition-colors",
      active ? "border-[hsl(174_72%_46%/0.3)] bg-[hsl(174_72%_46%/0.12)] text-[color:var(--aqt-teal)]" : "border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]",
      disabled && "cursor-not-allowed opacity-40"
    )}
  >
    {children}
  </button>
);

export default MatchesTable;
