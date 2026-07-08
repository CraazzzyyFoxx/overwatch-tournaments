"use client";

import React from "react";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";

import { TOURNAMENT_STATUS_ORDER } from "@/lib/tournament-status";
import type { TournamentStatus } from "@/types/tournament.types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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
  const t = useTranslations();
  const toggleType = (value: Exclude<TypeFilter, "all">) =>
    onTypeChange(typeFilter === value ? "all" : value);

  return (
    <div className="filters">
      <button
        type="button"
        className={`filter-chip${statusFilter === "all" ? " active" : ""}`}
        onClick={() => onStatusChange("all")}
      >
        {t("common.all")} <span className="count">{total}</span>
      </button>

      {TOURNAMENT_STATUS_ORDER.map((status) => {
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
            {t(`common.statusBadge.${status}`)} <span className="count">{count}</span>
          </button>
        );
      })}

      <div className="filter-divider" />

      <button
        type="button"
        className={`filter-chip${typeFilter === "standard" ? " active" : ""}`}
        onClick={() => toggleType("standard")}
      >
        {t("tournamentsList.filters.standard")} <span className="count">{standardCount}</span>
      </button>
      <button
        type="button"
        className={`filter-chip${typeFilter === "league" ? " active" : ""}`}
        onClick={() => toggleType("league")}
      >
        {t("common.league")} <span className="count">{leagueCount}</span>
      </button>

      <div className="filter-search">
        <Search width={13} height={13} />
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={t("tournamentsList.filters.searchPlaceholder")}
        />
      </div>

      <Select value={sortBy} onValueChange={(value) => onSortChange(value as SortBy)}>
        <SelectTrigger className="filter-sort h-8 w-[155px] shadow-none focus:ring-0 focus:ring-offset-0">
          <SelectValue placeholder={t("common.sortBy")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="latest">{t("tournamentsList.filters.sort.newest")}</SelectItem>
          <SelectItem value="oldest">{t("tournamentsList.filters.sort.oldest")}</SelectItem>
          <SelectItem value="participants">
            {t("tournamentsList.filters.sort.participants")}
          </SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
};

export default TournamentsFilters;
