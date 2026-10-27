"use client";

import { useTranslations } from "next-intl";
import { Card } from "@/components/ui/card";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";

export type Filter = "all" | "wins" | "losses" | "draws" | "group" | "playoffs" | "finals" | "mvp1" | "has_logs";

interface MatchesFilterBarProps {
  activeFilter: Filter;
  onApplyFilter: (key: Filter) => void;
  search: string;
  onSearchChange: (value: string) => void;
  /** "All games": the MVP filter reads one game's facts, so it is not offered. */
  allGames?: boolean;
}

const MatchesFilterBar = ({
  activeFilter,
  onApplyFilter,
  search,
  onSearchChange,
  allGames = false
}: MatchesFilterBarProps) => {
  const t = useTranslations();
  const filters: { key: Filter; label: string }[] = [
    { key: "all", label: t("common.all") },
    { key: "wins", label: t("users.matches.filters.wins") },
    { key: "losses", label: t("users.matches.filters.losses") },
    { key: "draws", label: t("users.matches.filters.draws") },
    { key: "group", label: t("users.matches.filters.group") },
    { key: "playoffs", label: t("users.matches.filters.playoffs") },
    { key: "finals", label: t("users.matches.filters.finals") },
    ...(allGames ? [] : [{ key: "mvp1" as const, label: t("users.matches.filters.mvp1") }]),
    { key: "has_logs", label: t("users.matches.filters.hasLogs") }
  ];
  return (
    <Card className="mb-3.5 p-2.5">
      <FilterChipGroup label={t("common.filters")}>
        {filters.map((f) => (
          <FilterChip key={f.key} active={activeFilter === f.key} onClick={() => onApplyFilter(f.key)}>
            {f.label}
          </FilterChip>
        ))}
        <SearchField
          label={t("users.matches.searchOpponentLabel")}
          placeholder={t("users.matches.searchOpponent")}
          value={search}
          onValueChange={onSearchChange}
          containerClassName="ml-auto min-w-[200px] max-w-[300px] flex-1"
          className="aqt-tnum"
        />
      </FilterChipGroup>
    </Card>
  );
};

export default MatchesFilterBar;
