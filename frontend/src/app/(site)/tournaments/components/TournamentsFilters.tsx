"use client";

import { LayoutGrid, List } from "lucide-react";
import { useTranslations } from "next-intl";

import { FilterChip } from "@/components/ui/filter-chip";
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
    /* Phone first: one horizontally scrollable chip row (wrapping chips used to
       strand the group divider on its own line), the search on its own full
       width line, and sort beside the view toggle. From `md` it is the single
       toolbar row again. */
    <div className="flex flex-col gap-2.5 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-2.5 md:flex-row md:flex-wrap md:items-center md:gap-2">
      <div className="tn-filter-chips -mx-2.5 flex items-center gap-x-5 gap-y-2 overflow-x-auto px-2.5 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden md:mx-0 md:flex-wrap md:overflow-visible md:px-0 md:pb-0">
        {/* Two groups, not one run of chips split by a hairline: status and
            format answer different questions, and a divider between them
            disappeared (or stranded itself) the moment the row wrapped. */}
        <div
          role="group"
          aria-label={t("common.status")}
          className="flex shrink-0 items-center gap-2"
        >
          <FilterChip
            active={statusFilter === "all"}
            count={total}
            onClick={() => onStatusChange("all")}
          >
            {t("common.all")}
          </FilterChip>

          {TOURNAMENT_STATUS_ORDER.map((status) => {
            const count = statusCounts[status] ?? 0;
            // A chip is only worth its place when it narrows something: an empty
            // bucket narrows to nothing, and one that matches the total ("All 77"
            // beside "Completed 77") is the same list under a second name. The
            // active chip always stays, or the filter could not be read or undone.
            if (statusFilter !== status && (count === 0 || count === total)) return null;

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
        </div>

        <div
          role="group"
          aria-label={t("tournamentsList.filters.typeLabel")}
          className="flex shrink-0 items-center gap-2"
        >
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
        </div>
      </div>

      <SearchField
        value={search}
        onValueChange={onSearchChange}
        label={t("common.searchLabel")}
        placeholder={t("tournamentsList.filters.searchPlaceholder")}
        containerClassName="md:ml-auto md:w-[240px]"
        className="max-md:h-10"
      />

      <div className="flex items-center gap-2">
        <Select value={sortBy} onValueChange={(value) => onSortChange(value as SortBy)}>
          <SelectTrigger
            aria-label={t("common.sortBy")}
            className="filter-sort h-8 w-[155px] shadow-none focus:ring-0 focus:ring-offset-0 max-md:h-10 max-md:w-full"
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

        {/* Hidden below `md`, where the page always renders cards: a toggle that
            cannot change what you see is a lie. The item labels are `sr-only`
            text, not `aria-label`: the icons alone give the radios no accessible
            name, and `ToggleGroupItem` forwards no ARIA props of its own. */}
        <ToggleGroup
          type="single"
          value={view}
          onValueChange={(value) => onViewChange(value as ViewMode)}
          aria-label={t("tournamentsList.view.label")}
          variant="pill"
          size="sm"
          className="max-md:hidden"
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
      </div>
    </div>
  );
};

export default TournamentsFilters;
