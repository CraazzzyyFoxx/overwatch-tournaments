"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { Users } from "lucide-react";
import { UserBestTeammate } from "@/types/user.types";
import { LogStatsName } from "@/types/stats.types";
import { CardSurface, heroInitials } from "@/app/(site)/users/components/redesign/atoms";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";

interface Props {
  teammates: UserBestTeammate[];
  selfName: string;
  totalCount: number;
  totalMaps: number;
}

const TEAMMATE_COLORS = [
  "linear-gradient(135deg, hsl(210 85% 72%), hsl(210 65% 46%))",
  "linear-gradient(135deg, hsl(340 85% 72%), hsl(340 65% 46%))",
  "linear-gradient(135deg, hsl(142 70% 64%), hsl(142 52% 40%))",
  "linear-gradient(135deg, hsl(38 95% 66%), hsl(38 82% 46%))",
  "linear-gradient(135deg, hsl(270 75% 72%), hsl(270 58% 48%))",
  "linear-gradient(135deg, hsl(0 80% 70%), hsl(0 62% 46%))"
];

const playerSlug = (name: string) => name.replace(/#/g, "-");

const formatStat = (value: number | null | undefined, digits: number) =>
  value != null && Number.isFinite(value) ? value.toFixed(digits) : "—";

const OverviewTeammatesSynergy = ({ teammates, selfName, totalCount, totalMaps }: Props) => {
  const [search, setSearch] = useState("");

  const top = teammates.slice(0, 6);
  if (top.length === 0) return null;

  const meInitials = heroInitials(selfName.split("#")[0]);

  return (
    <CardSurface
      flush
      title="Best teammates"
      icon={<Users size={15} />}
      action={
        <Dialog>
          <DialogTrigger asChild>
            <button type="button" className="aqt-seeall">
              All →
            </button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] p-0">
            <div className="aqt-player flex max-h-[80vh] flex-col">
              <DialogHeader className="border-b border-[color:var(--aqt-border)] px-5 py-4 text-left">
                <DialogTitle className="text-[color:var(--aqt-fg)]">Best teammates</DialogTitle>
                <DialogDescription className="text-[color:var(--aqt-fg-dim)]">
                  {totalCount} unique stack-mates · {totalMaps} maps together
                </DialogDescription>
              </DialogHeader>
              <AllTeammatesTable teammates={teammates} search={search} onSearchChange={setSearch} />
            </div>
          </DialogContent>
        </Dialog>
      }
    >
      <NetworkView top={top} meInitials={meInitials} totalCount={totalCount} totalMaps={totalMaps} />
    </CardSurface>
  );
};

// ─── Radial synergy graph ───────────────────────────────────────────────────────

const NetworkView = ({
  top,
  meInitials,
  totalCount,
  totalMaps
}: {
  top: UserBestTeammate[];
  meInitials: string;
  totalCount: number;
  totalMaps: number;
}) => {
  const nodes = useMemo(() => {
    const n = top.length;
    const maxApp = Math.max(...top.map((t) => t.tournaments), 1);
    return top.map((tm, i) => {
      // Evenly distribute around the centre, starting at the top.
      const angle = (2 * Math.PI * i) / n - Math.PI / 2;
      const left = 50 + Math.cos(angle) * 37;
      const top_ = 50 + Math.sin(angle) * 36;
      const strength = tm.tournaments / maxApp; // 0..1
      return { tm, i, left, top: top_, strength };
    });
  }, [top]);

  return (
    <>
      <div className="relative h-[300px]">
        <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
          <defs>
            <linearGradient id="syn-edge" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="hsl(38 95% 55% / 0.85)" />
              <stop offset="1" stopColor="hsl(174 72% 46% / 0.85)" />
            </linearGradient>
          </defs>
          {nodes.map(({ tm, left, top: top_, strength }) => (
            <line
              key={tm.user.id}
              x1={50}
              y1={50}
              x2={left}
              y2={top_}
              stroke="url(#syn-edge)"
              strokeWidth={1.2 + strength * 2.4}
              strokeLinecap="round"
              opacity={0.4 + strength * 0.45}
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>

        {/* Centre node (you) */}
        <div
          className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center"
          style={{ left: "50%", top: "50%" }}
        >
          <div
            className="flex h-[58px] w-[58px] items-center justify-center rounded-full aqt-display text-[17px] font-extrabold"
            style={{
              background: "linear-gradient(135deg, hsl(38 90% 62%), hsl(28 70% 42%))",
              color: "hsl(30 35% 10%)",
              boxShadow: "0 0 0 4px hsl(38 95% 55% / 0.22), 0 6px 18px hsl(220 60% 4% / 0.5)"
            }}
          >
            {meInitials}
          </div>
          <span className="mt-1.5 text-[10px] font-bold uppercase tracking-[0.16em]" style={{ color: "var(--aqt-amber)" }}>
            You
          </span>
        </div>

        {/* Teammate nodes */}
        {nodes.map(({ tm, i, left, top: top_, strength }) => {
          const [nm, tag] = tm.user.name.split("#");
          const size = 40 + strength * 12;
          return (
            <Link
              key={tm.user.id}
              href={`/users/${playerSlug(tm.user.name)}`}
              className="group absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1 text-center"
              style={{ left: `${left}%`, top: `${top_}%` }}
              title={tag ? `${nm}#${tag}` : nm}
            >
              <div
                className="flex items-center justify-center rounded-full aqt-display font-extrabold transition-transform group-hover:scale-110"
                style={{
                  width: size,
                  height: size,
                  fontSize: size * 0.34,
                  background: TEAMMATE_COLORS[i % TEAMMATE_COLORS.length],
                  color: "hsl(220 30% 8%)",
                  boxShadow: "0 4px 12px hsl(220 55% 4% / 0.45)"
                }}
              >
                {heroInitials(nm)}
              </div>
              <div className="leading-tight">
                <div className="max-w-[88px] truncate text-[11.5px] font-semibold text-[color:var(--aqt-fg)] group-hover:text-[color:var(--aqt-teal)]">
                  {nm}
                </div>
                <div className="aqt-mono text-[9.5px] text-[color:var(--aqt-fg-dim)]">
                  ×{tm.tournaments} · {(tm.winrate * 100).toFixed(0)}%
                </div>
              </div>
            </Link>
          );
        })}
      </div>
      <div className="aqt-mono flex justify-between border-t border-[color:var(--aqt-border)] px-[18px] py-2.5 text-[11px] text-[color:var(--aqt-fg-dim)]">
        <span>Edges sized by appearances</span>
        <span>
          {totalCount} unique · {totalMaps} maps
        </span>
      </div>
    </>
  );
};

// ─── Full teammates table (in the "All" modal) ──────────────────────────────────

const AllTeammatesTable = ({
  teammates,
  search,
  onSearchChange
}: {
  teammates: UserBestTeammate[];
  search: string;
  onSearchChange: (value: string) => void;
}) => {
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = [...teammates].sort((a, b) => b.tournaments - a.tournaments);
    if (!q) return rows;
    return rows.filter((t) => t.user.name.toLowerCase().includes(q));
  }, [teammates, search]);

  const perPage = 12;
  const [page, setPage] = useState(1);
  // Reset to first page when the search changes (render-time adjustment).
  const [prevSearch, setPrevSearch] = useState(search);
  if (search !== prevSearch) {
    setPrevSearch(search);
    setPage(1);
  }
  const pages = Math.max(1, Math.ceil(filtered.length / perPage));
  const safePage = Math.min(page, pages);
  const paged = filtered.slice((safePage - 1) * perPage, safePage * perPage);

  return (
    <div className="flex min-h-0 flex-col">
      <div className="border-b border-[color:var(--aqt-border)] px-5 py-3">
        <div className="relative">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            placeholder="Search teammates…"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.025)] px-3 py-1.5 pl-8 text-[13px] text-[color:var(--aqt-fg)] outline-none"
          />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        <table className="aqt-tnum w-full border-collapse text-[12.5px]">
          <thead className="sticky top-0 z-[1] bg-[color:var(--aqt-bg)]">
            <tr>
              {["Player", "×played", "Maps", "WR", "KDA", "MVP"].map((h, i) => (
                <th key={h} className={cnHeader(i === 0)}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paged.map((tm) => {
              const [tmName, tmTag] = tm.user.name.split("#");
              return (
                <tr key={tm.user.id} className="border-b border-[color:var(--aqt-border)] last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]">
                  <td className="px-3 py-2">
                    <Link href={`/users/${playerSlug(tm.user.name)}`} className="inline-flex items-center gap-1.5 hover:text-[color:var(--aqt-teal)]">
                      <span className="font-semibold text-[color:var(--aqt-fg)]">{tmName}</span>
                      {tmTag ? <span className="aqt-mono text-[10px] text-[color:var(--aqt-fg-faint)]">#{tmTag}</span> : null}
                    </Link>
                  </td>
                  <td className="aqt-mono px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">{tm.tournaments}</td>
                  <td className="aqt-mono px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">{tm.maps}</td>
                  <td
                    className="aqt-mono px-3 py-2 text-right font-semibold"
                    style={{
                      color: tm.winrate >= 0.55 ? "var(--aqt-emerald)" : tm.winrate < 0.45 ? "var(--aqt-rose)" : "var(--aqt-amber)"
                    }}
                  >
                    {(tm.winrate * 100).toFixed(0)}%
                  </td>
                  <td className="aqt-mono px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">
                    {formatStat(tm.stats?.[LogStatsName.KDA], 2)}
                  </td>
                  <td className="aqt-mono px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">
                    {formatStat(tm.stats?.[LogStatsName.Performance], 1)}
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-[12px] text-[color:var(--aqt-fg-dim)]">
                  No teammates match search
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      {filtered.length > perPage ? (
        <div className="flex items-center justify-between border-t border-[color:var(--aqt-border)] px-5 py-2.5">
          <span className="aqt-mono text-[11px] text-[color:var(--aqt-fg-dim)]">
            {(safePage - 1) * perPage + 1}–{Math.min(safePage * perPage, filtered.length)} of {filtered.length}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={safePage <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="aqt-mono inline-flex h-7 min-w-[28px] items-center justify-center rounded-[6px] border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[13px] text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-fg)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              ‹
            </button>
            <span className="aqt-mono px-1.5 text-[12px] text-[color:var(--aqt-fg-muted)]">
              {safePage} / {pages}
            </span>
            <button
              type="button"
              disabled={safePage >= pages}
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              className="aqt-mono inline-flex h-7 min-w-[28px] items-center justify-center rounded-[6px] border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[13px] text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-fg)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              ›
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
};

const cnHeader = (left: boolean) =>
  `aqt-mono border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] px-3 py-2.5 text-[10px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)] ${
    left ? "text-left" : "text-right"
  }`;

export default OverviewTeammatesSynergy;
