"use client";

import { LayoutGrid, List } from "lucide-react";
import { useTranslations } from "next-intl";

import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";
import { TOURNAMENT_STATUS_ORDER, getTournamentStatusMeta } from "@/lib/tournament/status";
import type { TournamentStatus } from "@/types/tournament.types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

export type StatusFilter = "all" | TournamentStatus;
export type TypeFilter = "all" | "standard" | "league";
export type SortBy = "latest" | "oldest" | "participants";
export type ViewMode = "cards" | "list";

/**
 * Dot colour per status bucket. Which bucket a status belongs to is a domain
 * fact (`getTournamentStatusMeta(...).variant`); what colour that bucket wears
 * is presentation, so it stays here.
 */
const VARIANT_DOT: Record<"live" | "upcoming" | "finished" | "draft", string> = {
  live: "var(--aqt-rose)",
  upcoming: "var(--aqt-amber)",
  finished: "var(--aqt-fg-dim)",
  draft: "var(--aqt-blue)"
};

interface TournamentsFiltersProps {
  /** Every visible tournament in the workspace, filters aside. From the facets. */
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
  view: ViewMode;
  onViewChange: (value: ViewMode) => void;
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
  onSortChange,
  view,
  onViewChange
}: TournamentsFiltersProps) => {
  const t = useTranslations();
  const toggleType = (value: Exclude<TypeFilter, "all">) =>
    onTypeChange(typeFilter === value ? "all" : value);

  return (
    <FilterChipGroup label={t("common.filters")} className="filters">
      <FilterChip
        active={statusFilter === "all"}
        count={total}
        onClick={() => onStatusChange("all")}
      >
        {t("common.all")}
      </FilterChip>

      {TOURNAMENT_STATUS_ORDER.map((status) => {
        const count = statusCounts[status] ?? 0;
        if (count === 0 && statusFilter !== status) return null;

        return (
          <FilterChip
            key={status}
            active={statusFilter === status}
            count={count}
            dotColor={VARIANT_DOT[getTournamentStatusMeta(status).variant]}
            onClick={() => onStatusChange(status)}
          >
            {t(`common.statusBadge.${status}`)}
          </FilterChip>
        );
      })}

      <div aria-hidden className="aqt-filter-divider" />

      <FilterChip
        active={typeFilter === "standard"}
        count={standardCount}
        onClick={() => toggleType("standard")}
      >
        {t("tournamentsList.filters.standard")}
      </FilterChip>
      <FilterChip
        active={typeFilter === "league"}
        count={leagueCount}
        onClick={() => toggleType("league")}
      >
        {t("common.league")}
      </FilterChip>

      <SearchField
        value={search}
        onValueChange={onSearchChange}
        label={t("common.searchLabel")}
        placeholder={t("tournamentsList.filters.searchPlaceholder")}
        containerClassName="ml-auto min-w-[200px] max-w-[300px] flex-1"
      />

      <Select value={sortBy} onValueChange={(value) => onSortChange(value as SortBy)}>
        <SelectTrigger
          aria-label={t("common.sortBy")}
          className="filter-sort h-8 w-[155px] shadow-none focus:ring-0 focus:ring-offset-0"
        >
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

      {/* The item labels are `sr-only` text, not `aria-label`: the icons alone
          give the radios no accessible name, and `ToggleGroupItem` forwards no
          ARIA props of its own. */}
      <ToggleGroup
        type="single"
        value={view}
        onValueChange={(value) => onViewChange(value as ViewMode)}
        aria-label={t("tournamentsList.view.label")}
        variant="pill"
        size="sm"
      >
        <ToggleGroupItem value="cards">
          <LayoutGrid aria-hidden width={14} height={14} />
          <span className="sr-only">{t("tournamentsList.view.cards")}</span>
        </ToggleGroupItem>
        <ToggleGroupItem value="list">
          <List aria-hidden width={14} height={14} />
          <span className="sr-only">{t("tournamentsList.view.list")}</span>
        </ToggleGroupItem>
      </ToggleGroup>
    </FilterChipGroup>
  );
};

export default TournamentsFilters;
