"use client";

import React from "react";
import { cn } from "@/lib/utils";

export type Filter = "all" | "wins" | "losses" | "draws" | "group" | "playoffs" | "finals" | "mvp1" | "has_logs";

export const FILTERS: { key: Filter; label: string }[] = [
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

interface MatchesFilterBarProps {
  activeFilter: Filter;
  onApplyFilter: (key: Filter) => void;
  search: string;
  onSearchChange: (value: string) => void;
}

const MatchesFilterBar = ({ activeFilter, onApplyFilter, search, onSearchChange }: MatchesFilterBarProps) => {
  return (
    <div className="aqt-filters mb-3.5">
      {FILTERS.map((f) => (
        <span
          key={f.key}
          className={cn("aqt-filter-chip", activeFilter === f.key && "active")}
          onClick={() => onApplyFilter(f.key)}
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
          onChange={(e) => onSearchChange(e.target.value)}
          className="aqt-tnum w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] px-3 py-1.5 pl-8 text-[13px] text-[color:var(--aqt-fg)] outline-none"
        />
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
      </div>
    </div>
  );
};

export default MatchesFilterBar;
