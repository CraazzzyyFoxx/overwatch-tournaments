"use client";

import React, { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import type { Hero } from "@/types/hero.types";
import HeroImage from "@/components/hero/HeroImage";
import { CardSurface, normalizeRole, type AqtRoleKey } from "@/app/(site)/users/components/shared/atoms";
import { formatSeconds, formatStatValue } from "@/app/(site)/users/components/heroes/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";

export interface HeroRow {
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

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "playtime", label: "Playtime" },
  { key: "winratePct", label: "Winrate" },
  { key: "kda", label: "KDA" },
  { key: "dmg10", label: "Dmg/10" },
  { key: "impact", label: "Impact" }
];

const ROLE_FILTERS: { key: "all" | AqtRoleKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "tank", label: "Tank" },
  { key: "damage", label: "Damage" },
  { key: "support", label: "Support" }
];

const num = (v: number | null) => (v == null || !Number.isFinite(v) ? -Infinity : v);

const metricValue = (key: SortKey, r: HeroRow): string => {
  switch (key) {
    case "playtime":
      return formatSeconds(r.playtime);
    case "winratePct":
      return r.winratePct == null ? "—" : `${r.winratePct.toFixed(0)}%`;
    case "kda":
      return r.kda == null ? "—" : r.kda.toFixed(2);
    case "dmg10":
      return r.dmg10 == null ? "—" : formatStatValue("dmg", r.dmg10);
    case "impact":
      return `${Math.round(r.impact * 100)}`;
  }
};

interface Props {
  rows: HeroRow[];
  selectedId: number;
  onSelect: (id: number) => void;
}

/** Sticky, sortable hero rail. Left column of the Heroes tab: ranks every
 *  tracked hero by the chosen metric (so cross-hero comparison stays possible)
 *  while keeping the detail panel beside it — switching heroes needs no scroll. */
const HeroRail = ({ rows, selectedId, onSelect }: Props) => {
  const [sort, setSort] = useState<SortKey>("playtime");
  const [role, setRole] = useState<"all" | AqtRoleKey>("all");
  const [query, setQuery] = useState("");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    let filtered = role === "all" ? rows : rows.filter((r) => normalizeRole(r.role) === role);
    if (q) filtered = filtered.filter((r) => r.hero.name.toLowerCase().includes(q));
    return [...filtered].sort((a, b) => num(b[sort]) - num(a[sort]));
  }, [rows, role, query, sort]);

  return (
    <CardSurface
      flush
      title="Your heroes"
      subtitle={`${rows.length} tracked`}
      className="xl:sticky xl:top-22"
    >
      <div className="flex flex-col gap-2 border-b border-[color:var(--aqt-border)] px-3 py-2.5">
        <div className="flex flex-wrap gap-1.5">
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
        </div>
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]">
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
            <input
              placeholder="Search…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.025)] px-3 py-1.5 pl-8 text-[13.5px] text-[color:var(--aqt-fg)] outline-none"
            />
          </div>
          <Select value={sort} onValueChange={(v) => setSort(v as SortKey)}>
            <SelectTrigger
              title="Sort heroes"
              className="aqt-mono h-9 w-[116px] shrink-0 border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.025)] text-[12px] text-[color:var(--aqt-fg)] shadow-none"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORT_OPTIONS.map((o) => (
                <SelectItem key={o.key} value={o.key}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="max-h-[calc(100vh-200px)] overflow-y-auto">
        {visible.map((r) => {
          const active = r.id === selectedId;
          return (
            <button
              key={r.id}
              type="button"
              onClick={() => onSelect(r.id)}
              className={cn(
                "grid w-full grid-cols-[36px_1fr_auto] items-center gap-2.5 border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-left transition-colors hover:bg-[hsl(0_0%_100%/0.025)]",
                active && "border-l-2 border-l-[color:var(--aqt-teal)] bg-[hsl(174_72%_46%/0.08)] pl-[10px]"
              )}
            >
              <HeroImage hero={r.hero} size="md" />
              <div className="min-w-0">
                <div className="truncate text-[14px] font-semibold text-[color:var(--aqt-fg)]">{r.hero.name}</div>
                <div className="truncate text-[12px] capitalize text-[color:var(--aqt-fg-dim)]">
                  {r.role} · WR {r.winratePct == null ? "—" : `${r.winratePct.toFixed(0)}%`} · {(r.share * 100).toFixed(0)}%
                </div>
                <div className="mt-1 h-1 w-full overflow-hidden rounded-sm bg-[hsl(0_0%_100%/0.05)]">
                  <div
                    className="h-full rounded-sm"
                    style={{
                      width: `${Math.round(r.impact * 100)}%`,
                      background:
                        r.impact >= 0.6 ? "var(--aqt-emerald)" : r.impact >= 0.4 ? "var(--aqt-amber)" : "var(--aqt-rose)"
                    }}
                  />
                </div>
              </div>
              <span className="aqt-mono text-right text-[14px] font-bold text-[color:var(--aqt-fg)]">
                {metricValue(sort, r)}
              </span>
            </button>
          );
        })}
        {visible.length === 0 ? (
          <div className="px-3 py-8 text-center text-[13px] text-[color:var(--aqt-fg-dim)]">No heroes</div>
        ) : null}
      </div>
    </CardSurface>
  );
};

export default HeroRail;
