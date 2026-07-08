"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

import SearchableImageSelect, {
  type SearchableImageOption
} from "@/app/(site)/users/compare/components/SearchableImageSelect";
import { AqtSelect } from "@/app/(site)/users/components/maps/atoms";

type SortKey = "winrate" | "count" | "name";
type OrderKey = "asc" | "desc";

const MIN_COUNT_OPTIONS = [1, 3, 5, 10];
const PER_PAGE_OPTIONS = [15, 30, -1];
const SORT_KEYS: SortKey[] = ["winrate", "count", "name"];

interface MapsFiltersProps {
  modes: string[];
  modeFilter: string | null;
  onModeFilterChange: (mode: string | null) => void;
  tournamentId: number | undefined;
  onTournamentIdChange: (id: number | undefined) => void;
  tournamentOptions: SearchableImageOption[];
  tournamentsLoading: boolean;
  tournamentsError: boolean;
  minCount: number;
  onMinCountChange: (value: number) => void;
  perPage: number;
  onPerPageChange: (value: number) => void;
  sort: SortKey;
  onSortChange: (value: SortKey) => void;
  order: OrderKey;
  onOrderToggle: () => void;
  search: string;
  onSearchChange: (value: string) => void;
}

const MapsFilters = ({
  modes,
  modeFilter,
  onModeFilterChange,
  tournamentId,
  onTournamentIdChange,
  tournamentOptions,
  tournamentsLoading,
  tournamentsError,
  minCount,
  onMinCountChange,
  perPage,
  onPerPageChange,
  sort,
  onSortChange,
  order,
  onOrderToggle,
  search,
  onSearchChange
}: MapsFiltersProps) => {
  const t = useTranslations();
  const sortLabels: Record<SortKey, string> = {
    winrate: t("users.maps.sortWinrate"),
    count: t("users.maps.sortGames"),
    name: t("users.maps.sortName")
  };
  return (
    <div className="aqt-filters">
      <span
        className={cn("aqt-filter-chip", modeFilter === null && "active")}
        onClick={() => onModeFilterChange(null)}
        role="button"
        tabIndex={0}
      >
        {t("users.maps.allModes")}
      </span>
      {modes.map((mode) => (
        <span
          key={mode}
          className={cn("aqt-filter-chip", modeFilter === mode && "active")}
          onClick={() => onModeFilterChange(mode)}
          role="button"
          tabIndex={0}
        >
          {mode}
        </span>
      ))}
      <span className="aqt-filter-divider" />

      <div className="w-48">
        <SearchableImageSelect
          value={tournamentId ? String(tournamentId) : undefined}
          onValueChange={(val) => onTournamentIdChange(val ? Number(val) : undefined)}
          options={tournamentOptions}
          placeholder={t("users.maps.allTournaments")}
          searchPlaceholder={t("users.maps.searchTournament")}
          isLoading={tournamentsLoading}
          disabled={tournamentsLoading || tournamentsError}
        />
      </div>

      <AqtSelect
        title={t("users.maps.minGamesTitle")}
        value={String(minCount)}
        onChange={(v) => onMinCountChange(Number(v))}
        options={MIN_COUNT_OPTIONS.map((n) => ({
          value: String(n),
          label: t("users.maps.minGames", { count: String(n) })
        }))}
      />
      <AqtSelect
        title={t("users.maps.rowsTitle")}
        value={String(perPage)}
        onChange={(v) => onPerPageChange(Number(v))}
        options={PER_PAGE_OPTIONS.map((n) => ({
          value: String(n),
          label: n === -1 ? t("users.maps.rowsAll") : t("users.maps.rows", { count: String(n) })
        }))}
      />
      <AqtSelect
        title={t("common.sortBy")}
        value={sort}
        onChange={(v) => onSortChange(v as SortKey)}
        options={SORT_KEYS.map((value) => ({
          value,
          label: t("users.maps.sort", { label: sortLabels[value] })
        }))}
      />
      <button
        type="button"
        onClick={onOrderToggle}
        title={order === "asc" ? t("common.ascending") : t("common.descending")}
        className="aqt-mono inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[14px] text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-fg)]"
      >
        {order === "asc" ? "↑" : "↓"}
      </button>

      <div className="filter-search relative ml-auto min-w-[180px] max-w-[300px] flex-1">
        <input
          placeholder={t("users.maps.searchMaps")}
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] px-3 py-1.5 pl-8 text-[14px] outline-none"
        />
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
      </div>
    </div>
  );
};

export default MapsFilters;
