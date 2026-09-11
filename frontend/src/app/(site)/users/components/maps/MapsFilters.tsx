"use client";

import { useTranslations } from "next-intl";
import { ArrowDown, ArrowUp } from "lucide-react";

import SearchableImageSelect, {
  type SearchableImageOption
} from "@/components/ui/searchable-image-select";
import { SearchField } from "@/components/ui/search-field";
import { AqtSelect } from "@/app/(site)/users/components/maps/atoms";

type SortKey = "winrate" | "count" | "name";
type OrderKey = "asc" | "desc";

const MIN_COUNT_OPTIONS = [1, 3, 5, 10];
const PER_PAGE_OPTIONS = [15, 30, -1];
const SORT_KEYS: SortKey[] = ["winrate", "count", "name"];

interface MapsFiltersProps {
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
    <div className="aqt-filters rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-2.5">
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
        aria-label={t("common.sortDirection", {
          current: order === "asc" ? t("common.ascending") : t("common.descending"),
          next: order === "asc" ? t("common.descending") : t("common.ascending")
        })}
        className="aqt-tnum inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:text-[color:var(--aqt-fg)] focus-visible:border-[color:var(--aqt-teal)] focus-visible:ring-2 focus-visible:ring-[color:color-mix(in_srgb,var(--aqt-teal)_25%,transparent)]"
      >
        {order === "asc" ? <ArrowUp aria-hidden className="size-3.5" /> : <ArrowDown aria-hidden className="size-3.5" />}
      </button>

      <SearchField
        label={t("users.maps.searchLabel")}
        placeholder={t("users.maps.searchMaps")}
        value={search}
        onValueChange={onSearchChange}
        containerClassName="ml-auto min-w-[180px] max-w-[300px] flex-1"
      />
    </div>
  );
};

export default MapsFilters;
