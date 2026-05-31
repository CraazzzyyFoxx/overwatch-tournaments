"use client";

import React from "react";
import { Search } from "lucide-react";

import { TOURNAMENT_STATUS_ORDER, TOURNAMENT_STATUS_META } from "@/lib/tournament-status";
import type { TournamentStatus } from "@/types/tournament.types";

export type StatusFilter = "all" | TournamentStatus;
export type TypeFilter = "all" | "standard" | "league";
export type SortBy = "latest" | "oldest" | "participants";

interface TournamentsFiltersProps {
  total: number;
  statusCounts: Record<TournamentStatus, number>;
  statusFilter: StatusFilter;
  onStatusChange: (value: StatusFilter) => void;
  typeFilter: TypeFilter;
  leagueCount: number;
  standardCount: number;
  onTypeChange: (value: TypeFilter) => void;
  search: string;
  onSearchChange: (value: string) => void;
  sortBy: SortBy;
  onSortChange: (value: SortBy) => void;
}

const TournamentsFilters = ({
  total,
  statusCounts,
  statusFilter,
  onStatusChange,
  typeFilter,
  leagueCount,
  standardCount,
  onTypeChange,
  search,
  onSearchChange,
  sortBy,
  onSortChange
}: TournamentsFiltersProps) => {
  const toggleType = (value: Exclude<TypeFilter, "all">) =>
    onTypeChange(typeFilter === value ? "all" : value);

  return (
    <div className="filters">
      <button
        type="button"
        className={`filter-chip${statusFilter === "all" ? " active" : ""}`}
        onClick={() => onStatusChange("all")}
      >
        All <span className="count">{total}</span>
      </button>

      {TOURNAMENT_STATUS_ORDER.map((status) => {
        const meta = TOURNAMENT_STATUS_META[status];
        const count = statusCounts[status] ?? 0;
        if (count === 0 && statusFilter !== status) return null;

        const designClass =
          status === "live" || status === "playoffs"
            ? "live"
            : status === "registration" || status === "check_in"
              ? "upcoming"
              : status === "completed" || status === "archived"
                ? "finished"
                : "draft";

        return (
          <button
            key={status}
            type="button"
            className={`filter-chip${statusFilter === status ? " active" : ""}`}
            onClick={() => onStatusChange(status)}
          >
            <span className={`dot ${designClass}`} />
            {meta.badgeLabel} <span className="count">{count}</span>
          </button>
        );
      })}

      <div className="filter-divider" />

      <button
        type="button"
        className={`filter-chip${typeFilter === "standard" ? " active" : ""}`}
        onClick={() => toggleType("standard")}
      >
        Standard <span className="count">{standardCount}</span>
      </button>
      <button
        type="button"
        className={`filter-chip${typeFilter === "league" ? " active" : ""}`}
        onClick={() => toggleType("league")}
      >
        League <span className="count">{leagueCount}</span>
      </button>

      <div className="filter-search">
        <Search width={13} height={13} />
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Filter by name or number…"
        />
      </div>

      <select
        className="filter-sort"
        value={sortBy}
        onChange={(event) => onSortChange(event.target.value as SortBy)}
        aria-label="Sort tournaments"
      >
        <option value="latest">Newest first</option>
        <option value="oldest">Oldest first</option>
        <option value="participants">Most participants</option>
      </select>
    </div>
  );
};

export default TournamentsFilters;
