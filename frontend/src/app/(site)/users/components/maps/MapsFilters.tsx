"use client";

import { useTranslations } from "next-intl";
import { ArrowDown, ArrowUp } from "lucide-react";

import { TournamentCombobox } from "@/components/tournaments/TournamentCombobox";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SearchField } from "@/components/ui/search-field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type SortKey = "winrate" | "count" | "name";
type OrderKey = "asc" | "desc";

const MIN_COUNT_OPTIONS = [1, 3, 5, 10];
const PER_PAGE_OPTIONS = [15, 30, -1];
const SORT_KEYS: SortKey[] = ["winrate", "count", "name"];

interface MapsFiltersProps {
  tournamentId: number | undefined;
  onTournamentIdChange: (id: number | undefined) => void;
  tournaments: readonly { id: number; name: string }[];
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
  tournaments,
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
    <Card className="flex flex-wrap items-center gap-2 p-2.5">
      <div className="w-48">
        <TournamentCombobox
          tournaments={tournaments}
          value={tournamentId}
          onValueChange={onTournamentIdChange}
          size="sm"
          variant="surface"
        />
      </div>

      <Select value={String(minCount)} onValueChange={(v) => onMinCountChange(Number(v))}>
        <SelectTrigger size="sm" variant="surface" title={t("users.maps.minGamesTitle")} className="w-[150px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {MIN_COUNT_OPTIONS.map((n) => (
            <SelectItem key={n} value={String(n)}>
              {t("users.maps.minGames", { count: String(n) })}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={String(perPage)} onValueChange={(v) => onPerPageChange(Number(v))}>
        <SelectTrigger size="sm" variant="surface" title={t("users.maps.rowsTitle")} className="w-[150px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PER_PAGE_OPTIONS.map((n) => (
            <SelectItem key={n} value={String(n)}>
              {n === -1 ? t("users.maps.rowsAll") : t("users.maps.rows", { count: String(n) })}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={sort} onValueChange={(v) => onSortChange(v as SortKey)}>
        <SelectTrigger size="sm" variant="surface" title={t("common.sortBy")} className="w-[150px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {SORT_KEYS.map((value) => (
            <SelectItem key={value} value={value}>
              {t("users.maps.sort", { label: sortLabels[value] })}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        variant="outline"
        size="icon-sm"
        onClick={onOrderToggle}
        aria-label={t("common.sortDirection", {
          current: order === "asc" ? t("common.ascending") : t("common.descending"),
          next: order === "asc" ? t("common.descending") : t("common.ascending")
        })}
      >
        {order === "asc" ? <ArrowUp aria-hidden /> : <ArrowDown aria-hidden />}
      </Button>

      <SearchField
        label={t("users.maps.searchLabel")}
        placeholder={t("users.maps.searchMaps")}
        value={search}
        onValueChange={onSearchChange}
        containerClassName="ml-auto min-w-[180px] max-w-[300px] flex-1"
      />
    </Card>
  );
};

export default MapsFilters;
