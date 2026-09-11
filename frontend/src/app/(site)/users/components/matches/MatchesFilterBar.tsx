"use client";

import { useTranslations } from "next-intl";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";

export type Filter = "all" | "wins" | "losses" | "draws" | "group" | "playoffs" | "finals" | "mvp1" | "has_logs";

interface MatchesFilterBarProps {
  activeFilter: Filter;
  onApplyFilter: (key: Filter) => void;
  search: string;
  onSearchChange: (value: string) => void;
}

const MatchesFilterBar = ({ activeFilter, onApplyFilter, search, onSearchChange }: MatchesFilterBarProps) => {
  const t = useTranslations();
  const filters: { key: Filter; label: string }[] = [
    { key: "all", label: t("common.all") },
    { key: "wins", label: t("users.matches.filters.wins") },
    { key: "losses", label: t("users.matches.filters.losses") },
    { key: "draws", label: t("users.matches.filters.draws") },
    { key: "group", label: t("users.matches.filters.group") },
    { key: "playoffs", label: t("users.matches.filters.playoffs") },
    { key: "finals", label: t("users.matches.filters.finals") },
    { key: "mvp1", label: t("users.matches.filters.mvp1") },
    { key: "has_logs", label: t("users.matches.filters.hasLogs") }
  ];
  return (
    <FilterChipGroup
      label={t("common.filters")}
      className="mb-3.5 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-2.5"
    >
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
  );
};

export default MatchesFilterBar;
