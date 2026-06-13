"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useDebounce } from "use-debounce";
import { cn } from "@/lib/utils";
import { EncounterWithUserStats } from "@/types/user.types";
import {
  CardSurface,
  ResTag,
  ScoreCell,
  StagePill
} from "@/app/(site)/users/components/shared/atoms";
import MvpMatchPill from "@/app/(site)/users/components/matches/MvpMatchPill";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import { HeroStrip } from "@/components/hero/HeroImage";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ArrowLeftRight, ListOrdered } from "lucide-react";
import type { Hero } from "@/types/hero.types";

interface Props {
  encounters: EncounterWithUserStats[];
  total: number;
  page: number;
  perPage: number;
  selfUserId: number;
}

/** Server-side Matches-tab filters (mirrors the encounters endpoint params). */
export interface MatchesFilters {
  result?: "win" | "loss" | "draw";
  stage?: "group" | "playoffs" | "finals";
  mvp1?: boolean;
  hasLogs?: boolean;
  opponent?: string;
}

type Filter = "all" | "wins" | "losses" | "draws" | "group" | "playoffs" | "finals" | "mvp1" | "has_logs";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "wins", label: "Wins" },
  { key: "losses", label: "Losses" },
  { key: "draws", label: "Draws" },
  { key: "group", label: "Group" },
  { key: "playoffs", label: "Playoffs" },
  { key: "finals", label: "Finals" },
  { key: "mvp1", label: "MVP 1st" },
  { key: "has_logs", label: "Has logs" }
];

const stageKindFor = (name: string | undefined): "group" | "playoffs" | "finals" | "default" => {
  if (!name) return "default";
  const lower = name.toLowerCase();
  if (lower.includes("final")) return "finals";
  if (lower.includes("playoff") || lower.includes("bracket")) return "playoffs";
  if (lower.includes("group") || lower.match(/^[a-h]$/i)) return "group";
  return "default";
};

const stageLabel = (name: string | undefined): string => name?.trim() || "—";

const MatchesTable = ({ encounters, total, page, perPage, selfUserId }: Props) => {
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

  // Most-fought opponents
  const opponentStats = useMemo(() => {
    const map = new Map<string, { name: string; wins: number; losses: number; draws: number }>();
    encounters.forEach((enc) => {
      const isUserHome = (enc.home_team?.players ?? []).some((p) => p.user_id === selfUserId);
      const oppName = isUserHome ? enc.away_team?.name : enc.home_team?.name;
      if (!oppName) return;
      const userScore = isUserHome ? enc.score.home : enc.score.away;
      const oppScore = isUserHome ? enc.score.away : enc.score.home;
      const entry = map.get(oppName) ?? { name: oppName, wins: 0, losses: 0, draws: 0 };
      if (userScore > oppScore) entry.wins++;
      else if (userScore < oppScore) entry.losses++;
      else entry.draws++;
      map.set(oppName, entry);
    });
    return Array.from(map.values()).sort((a, b) =>
      (b.wins + b.losses + b.draws) - (a.wins + a.losses + a.draws)
    ).slice(0, 8);
  }, [encounters, selfUserId]);

  // Stage stats
  const stageStats = useMemo(() => {
    const acc = { group: { w: 0, l: 0 }, playoffs: { w: 0, l: 0 }, finals: { w: 0, l: 0 } };
    encounters.forEach((enc) => {
      const isUserHome = (enc.home_team?.players ?? []).some((p) => p.user_id === selfUserId);
      const userScore = isUserHome ? enc.score.home : enc.score.away;
      const oppScore = isUserHome ? enc.score.away : enc.score.home;
      const kind = stageKindFor(enc.stage_item?.name ?? enc.stage?.name);
      if (kind === "default") return;
      if (userScore > oppScore) acc[kind].w++;
      else if (userScore < oppScore) acc[kind].l++;
    });
    return acc;
  }, [encounters, selfUserId]);

  return (
    <div className="aqt-player">
      <div className="aqt-filters mb-3.5">
        {FILTERS.map((f) => (
          <span
            key={f.key}
            className={cn("aqt-filter-chip", activeFilter === f.key && "active")}
            onClick={() => applyFilter(f.key)}
            role="button"
            tabIndex={0}
          >
            {f.label}
          </span>
        ))}
        <div className="filter-search relative ml-auto min-w-[200px] max-w-[300px] flex-1">
          <input
            placeholder="Search opponent…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="aqt-tnum w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] px-3 py-1.5 pl-8 text-[13px] text-[color:var(--aqt-fg)] outline-none"
          />
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
        </div>
      </div>

      <div className="grid grid-cols-1 items-start gap-3.5 xl:grid-cols-[1fr_320px]">
        <CardSurface flush>
          <div className="overflow-x-auto">
            <table className="aqt-tnum w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  {["Tournament", "Stage", "Match", "Score", "Heroes", "MVP", "Close.", "Logs"].map((h) => (
                    <th
                      key={h}
                      className="aqt-mono border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.015)] px-3.5 py-3 text-left text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {encounters.map((enc) => {
                  const isUserHome = (enc.home_team?.players ?? []).some((p) => p.user_id === selfUserId);
                  const userScore = isUserHome ? enc.score.home : enc.score.away;
                  const oppScore = isUserHome ? enc.score.away : enc.score.home;
                  const kind = stageKindFor(enc.stage_item?.name ?? enc.stage?.name);
                  const scoreKind = userScore > oppScore ? "win" : userScore < oppScore ? "loss" : "draw";
                  const resKind = userScore > oppScore ? "w" : userScore < oppScore ? "l" : "d";
                  const tNum = enc.tournament?.number ?? enc.tournament_id;
                  const opponentName = isUserHome ? enc.away_team?.name : enc.home_team?.name;
                  const userTeamName = isUserHome ? enc.home_team?.name : enc.away_team?.name;
                  const heroSet = new Set<string>();
                  const heroList: Pick<Hero, "name" | "image_path" | "role">[] = [];
                  (enc.matches ?? []).forEach((match) => {
                    // MatchWithUserStats.heroes is already the viewer's heroes for
                    // this match (computed server-side from MatchStatistics).
                    (match.heroes ?? []).forEach((h) => {
                      if (!heroSet.has(h.name)) {
                        heroSet.add(h.name);
                        heroList.push({ name: h.name, image_path: h.image_path, role: h.type ?? h.role });
                      }
                    });
                  });

                  const mvpMatches = (enc.matches ?? []).filter((m) => m.performance != null);

                  return (
                    <tr
                      key={enc.id}
                      onClick={() => router.push(`/encounters/${enc.id}`)}
                      className="cursor-pointer border-b border-[hsl(215_20%_10%)] transition-colors last:border-b-0 hover:bg-[hsl(0_0%_100%/0.025)]"
                    >
                      <td className="px-3.5 py-3">
                        <Link
                          href={`/tournaments/${enc.tournament_id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="aqt-mono inline-flex items-center gap-1.5 rounded-[5px] border px-2 py-0.5 text-[10.5px] font-bold"
                          style={{
                            background: "hsl(174 72% 46% / 0.08)",
                            borderColor: "hsl(174 72% 46% / 0.25)",
                            color: "var(--aqt-teal)"
                          }}
                        >
                          T {tNum}
                        </Link>
                      </td>
                      <td className="px-3.5 py-3">
                        <StagePill kind={kind}>{stageLabel(enc.stage_item?.name ?? enc.stage?.name)}</StagePill>
                      </td>
                      <td className="px-3.5 py-3">
                        <span className="inline-flex items-center gap-2">
                          <ResTag kind={resKind} />
                          <Link
                            href={`/encounters/${enc.id}`}
                            onClick={(e) => e.stopPropagation()}
                            className="hover:text-[color:var(--aqt-teal)]"
                          >
                            {userTeamName} vs {opponentName}
                          </Link>
                        </span>
                      </td>
                      <td className="px-3.5 py-3">
                        <ScoreCell kind={scoreKind} value={`${userScore}-${oppScore}`} />
                      </td>
                      <td className="px-3.5 py-3">
                        <HeroStrip heroes={heroList} size="sm" limit={4} />
                      </td>
                      <td className="px-3.5 py-3">
                        {mvpMatches.length > 0 ? (
                          <TooltipProvider delayDuration={150}>
                            <span className="inline-flex items-center gap-1">
                              {mvpMatches.map((m) => (
                                <MvpMatchPill key={m.id} match={m} />
                              ))}
                            </span>
                          </TooltipProvider>
                        ) : (
                          <span className="aqt-mono text-[color:var(--aqt-fg-faint)]">—</span>
                        )}
                      </td>
                      <td className="aqt-mono px-3.5 py-3 text-[11px] text-[color:var(--aqt-fg-dim)]">
                        {enc.closeness != null ? `${(enc.closeness * 100).toFixed(0)}%` : "—"}
                      </td>
                      <td className="px-3.5 py-3" onClick={(e) => e.stopPropagation()}>
                        <MatchLogIndicator
                          hasLogs={enc.has_logs}
                          logs={
                            enc.has_logs
                              ? (enc.matches ?? []).map((m, i) => ({ matchId: m.id, label: m.map?.name ?? `Map ${i + 1}` }))
                              : undefined
                          }
                        />
                      </td>
                    </tr>
                  );
                })}
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
            <span className="aqt-mono text-[12px] text-[color:var(--aqt-fg-dim)]">
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

        <aside className="flex flex-col gap-3.5 xl:sticky xl:top-22">
          <CardSurface flush title="Most-fought opponents" icon={<ArrowLeftRight size={15} />}>
            {opponentStats.map((opp, i) => (
              <div key={opp.name} className="aqt-opp-row">
                <span className="aqt-rank">{String(i + 1).padStart(2, "0")}</span>
                <span className="aqt-nm">{opp.name}</span>
                <span className="aqt-wl">
                  {Array.from({ length: opp.wins }).map((_, idx) => <span key={`w${idx}`} className="b w" />)}
                  {Array.from({ length: opp.losses }).map((_, idx) => <span key={`l${idx}`} className="b l" />)}
                  {Array.from({ length: opp.draws }).map((_, idx) => <span key={`d${idx}`} className="b d" />)}
                </span>
                <span className="aqt-pct">
                  {opp.wins}-{opp.losses}{opp.draws > 0 ? `-${opp.draws}` : ""}
                </span>
              </div>
            ))}
            {opponentStats.length === 0 ? (
              <div className="p-4 text-center text-[12px] text-[color:var(--aqt-fg-dim)]">No data</div>
            ) : null}
          </CardSurface>

          <CardSurface flush title="By stage" icon={<ListOrdered size={15} />}>
            {(["group", "playoffs", "finals"] as const).map((k) => {
              const stats = stageStats[k];
              const total = stats.w + stats.l;
              const winrate = total > 0 ? (stats.w / total) * 100 : 0;
              return (
                <div key={k} className="aqt-opp-row" style={{ gridTemplateColumns: "1fr auto auto" }}>
                  <span className="aqt-nm inline-flex items-center gap-2">
                    <StagePill kind={k}>{k.charAt(0).toUpperCase() + k.slice(1)}</StagePill>
                  </span>
                  <span className="aqt-pct">{stats.w}-{stats.l}</span>
                  <span
                    className="aqt-mono text-[11px] font-bold"
                    style={{
                      color: winrate > 55 ? "var(--aqt-emerald)" : winrate < 45 ? "var(--aqt-rose)" : "var(--aqt-amber)"
                    }}
                  >
                    {total > 0 ? `${winrate.toFixed(0)}%` : "—"}
                  </span>
                </div>
              );
            })}
          </CardSurface>
        </aside>
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
      "aqt-mono inline-flex h-8 min-w-[32px] items-center justify-center rounded-[6px] border px-2 text-[12px] transition-colors",
      active ? "border-[hsl(174_72%_46%/0.3)] bg-[hsl(174_72%_46%/0.12)] text-[color:var(--aqt-teal)]" : "border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]",
      disabled && "cursor-not-allowed opacity-40"
    )}
  >
    {children}
  </button>
);

export default MatchesTable;
