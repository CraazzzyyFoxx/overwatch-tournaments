"use client";

import React, { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import type { Hero } from "@/types/hero.types";
import HeroImage from "@/components/hero/HeroImage";
import { CardSurface, normalizeRole, type AqtRoleKey } from "@/app/(site)/users/components/shared/atoms";
import { formatSeconds, formatStatValue } from "@/app/(site)/users/components/heroes/utils";

export interface HeroOverviewRow {
  id: number;
  hero: Hero;
  role: string;
  playtime: number;
  share: number;
  winratePct: number | null;
  kda: number | null;
  dmg10: number | null;
  /** Share of comparable stats where the player beats the global average (0..1). */
  impact: number;
}

type SortKey = "playtime" | "winratePct" | "kda" | "dmg10" | "impact";

const COLUMNS: { key: SortKey; label: string; align: "left" | "right" }[] = [
  { key: "playtime", label: "Time", align: "right" },
  { key: "winratePct", label: "WR", align: "right" },
  { key: "kda", label: "KDA", align: "right" },
  { key: "dmg10", label: "Dmg/10", align: "right" },
  { key: "impact", label: "Impact", align: "right" }
];

const ROLE_FILTERS: { key: "all" | AqtRoleKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "tank", label: "Tank" },
  { key: "damage", label: "Damage" },
  { key: "support", label: "Support" }
];

const num = (v: number | null) => (v == null || !Number.isFinite(v) ? -Infinity : v);

interface Props {
  rows: HeroOverviewRow[];
  selectedId: number;
  onSelect: (id: number) => void;
}

/** Cross-hero leaderboard: every tracked hero in one sortable, role-filterable
 *  table so "which hero carries me" is answerable at a glance. Clicking a row
 *  drives the detail panel below. */
const HeroOverviewTable = ({ rows, selectedId, onSelect }: Props) => {
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "playtime", dir: "desc" });
  const [role, setRole] = useState<"all" | AqtRoleKey>("all");
  const [query, setQuery] = useState("");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    let filtered = role === "all" ? rows : rows.filter((r) => normalizeRole(r.role) === role);
    if (q) filtered = filtered.filter((r) => r.hero.name.toLowerCase().includes(q));
    const sign = sort.dir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => (num(a[sort.key]) - num(b[sort.key])) * sign);
  }, [rows, role, query, sort]);

  const toggleSort = (key: SortKey) =>
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === "desc" ? "asc" : "desc" } : { key, dir: "desc" }));

  const arrow = (key: SortKey) => (sort.key === key ? (sort.dir === "desc" ? " ↓" : " ↑") : "");

  return (
    <CardSurface flush title="Your heroes" subtitle={`${rows.length} tracked`}>
      <div className="flex flex-wrap items-center gap-1.5 border-b border-[color:var(--aqt-border)] px-[18px] py-2.5">
        {ROLE_FILTERS.map((rf) => (
          <span
            key={rf.key}
            role="button"
            tabIndex={0}
            onClick={() => setRole(rf.key)}
            className={cn("aqt-filter-chip", role === rf.key && "active")}
          >
            {rf.label}
          </span>
        ))}
        <div className="relative ml-auto min-w-[160px] max-w-[220px] flex-1">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            placeholder="Search heroes…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.025)] px-3 py-1.5 pl-8 text-[13.5px] text-[color:var(--aqt-fg)] outline-none"
          />
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="aqt-tnum w-full border-collapse text-[14px]">
          <thead>
            <tr>
              <th className="aqt-mono border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.015)] px-[18px] py-2.5 text-left text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
                Hero
              </th>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  role="button"
                  tabIndex={0}
                  onClick={() => toggleSort(c.key)}
                  className={cn(
                    "aqt-mono cursor-pointer select-none border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.015)] px-3.5 py-2.5 text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)] hover:text-[color:var(--aqt-fg-muted)]",
                    c.align === "right" ? "text-right" : "text-left",
                    sort.key === c.key && "text-[color:var(--aqt-fg-muted)]"
                  )}
                >
                  {c.label}
                  {arrow(c.key)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => {
              const active = r.id === selectedId;
              return (
                <tr
                  key={r.id}
                  onClick={() => onSelect(r.id)}
                  className={cn(
                    "cursor-pointer border-b border-[color:var(--aqt-border)] transition-colors hover:bg-[hsl(0_0%_100%/0.025)]",
                    active && "bg-[hsl(174_72%_46%/0.08)]"
                  )}
                >
                  <td className={cn("px-[18px] py-2.5", active && "border-l-2 border-l-[color:var(--aqt-teal)] pl-4")}>
                    <div className="flex items-center gap-2.5">
                      <HeroImage hero={r.hero} size="md" />
                      <div className="flex min-w-0 flex-col">
                        <span className="truncate text-[14px] font-semibold text-[color:var(--aqt-fg)]">{r.hero.name}</span>
                        <span className="text-[12px] capitalize text-[color:var(--aqt-fg-dim)]">
                          {r.role} · {(r.share * 100).toFixed(0)}%
                        </span>
                      </div>
                    </div>
                  </td>
                  <td className="aqt-mono px-3.5 py-2.5 text-right text-[13px] text-[color:var(--aqt-fg-muted)]">
                    {formatSeconds(r.playtime)}
                  </td>
                  <td className="aqt-mono px-3.5 py-2.5 text-right text-[14px] font-semibold">
                    {r.winratePct == null ? "—" : `${r.winratePct.toFixed(0)}%`}
                  </td>
                  <td className="aqt-mono px-3.5 py-2.5 text-right text-[14px]">
                    {r.kda == null ? "—" : r.kda.toFixed(2)}
                  </td>
                  <td className="aqt-mono px-3.5 py-2.5 text-right text-[14px]">
                    {r.dmg10 == null ? "—" : formatStatValue("dmg", r.dmg10)}
                  </td>
                  <td className="px-3.5 py-2.5">
                    <div className="ml-auto flex w-[72px] items-center gap-1.5">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-sm bg-[hsl(0_0%_100%/0.06)]">
                        <div
                          className="h-full rounded-sm"
                          style={{
                            width: `${Math.round(r.impact * 100)}%`,
                            background:
                              r.impact >= 0.6 ? "var(--aqt-emerald)" : r.impact >= 0.4 ? "var(--aqt-amber)" : "var(--aqt-rose)"
                          }}
                        />
                      </div>
                      <span className="aqt-mono w-7 text-right text-[11px] text-[color:var(--aqt-fg-dim)]">
                        {Math.round(r.impact * 100)}
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
            {visible.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length + 1} className="px-[18px] py-8 text-center text-[13px] text-[color:var(--aqt-fg-dim)]">
                  No heroes for this role
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </CardSurface>
  );
};

export default HeroOverviewTable;
