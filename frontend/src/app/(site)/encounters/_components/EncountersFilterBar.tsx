"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";
import { cn } from "@/lib/utils";
import type { EncounterOverview } from "@/types/encounter.types";
import type { LookupItem } from "@/types/pagination.types";

import type { EncounterFilterState } from "./encounters.helpers";
import { countLabel } from "./encounters.model";
import styles from "./Encounters.module.css";

/**
 * Status chips, the scoping selects, search and sort.
 *
 * Status is owned by these chips alone. There used to be a "Status: …" select
 * beside them setting the same field with a different option set, so the two
 * controls silently overwrote each other — and the select added a third "All".
 */
export function EncountersFilterBar({
  filters,
  searchValue,
  kpis,
  tournaments,
  onSearchChange,
  onPatch
}: Readonly<{
  filters: EncounterFilterState;
  searchValue: string;
  kpis: EncounterOverview["kpis"];
  tournaments: LookupItem[];
  onSearchChange: (value: string) => void;
  onPatch: (patch: Partial<EncounterFilterState>) => void;
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const statusChips: Array<{ id: string; label: string; count?: number; value: string }> = [
    { id: "live", label: t("common.live"), count: kpis.live_now_count, value: "live" },
    {
      id: "pending",
      label: t("encounters.filter.statusPending"),
      count: kpis.upcoming_count,
      value: "pending"
    },
    { id: "completed", label: t("encounters.filter.statusFinal"), value: "completed" },
    { id: "open", label: t("encounters.filter.statusOpen"), value: "open" }
  ];

  return (
    <section aria-label={t("encounters.aria.filters")}>
      <div className={styles.filters}>
        <FilterChipGroup label={t("common.status")}>
          {statusChips.map((chip) => (
            <FilterChip
              key={chip.id}
              active={filters.status === chip.value}
              count={chip.count == null ? undefined : countLabel(format, chip.count)}
              onClick={() =>
                onPatch({ status: filters.status === chip.value ? null : chip.value })
              }
            >
              {chip.label}
            </FilterChip>
          ))}
        </FilterChipGroup>
        <span className={styles.filterDivider} />
        <FilterSelect
          label={t("common.tournament")}
          value={filters.tournament_id == null ? "all" : String(filters.tournament_id)}
          onValueChange={(value) =>
            onPatch({ tournament_id: value === "all" ? null : Number(value) })
          }
          items={[
            ["all", t("encounters.filter.tournamentAny")] as [string, string],
            ...tournaments.map(
              (item) =>
                [
                  String(item.id),
                  t("encounters.filter.tournamentNamed", { name: item.name })
                ] as [string, string]
            )
          ]}
        />
        <FilterSelect
          label={t("encounters.filter.bestOf")}
          value={filters.best_of == null ? "all" : String(filters.best_of)}
          onValueChange={(value) => onPatch({ best_of: value === "all" ? null : Number(value) })}
          items={[
            ["all", t("encounters.filter.bestOfAny")],
            ["3", t("encounters.filter.bestOfValue", { count: "3" })],
            ["5", t("encounters.filter.bestOfValue", { count: "5" })],
            ["7", t("encounters.filter.bestOfValue", { count: "7" })]
          ]}
        />
        <FilterSelect
          label={t("encounters.col.closeness")}
          value={filters.closeness_min == null ? "all" : String(filters.closeness_min)}
          onValueChange={(value) =>
            onPatch({ closeness_min: value === "all" ? null : Number(value) })
          }
          items={[
            ["all", t("encounters.filter.closenessAny")],
            ["0.4", t("encounters.filter.closenessMin", { pct: "40" })],
            ["0.6", t("encounters.filter.closenessMin", { pct: "60" })],
            ["0.8", t("encounters.filter.closenessMin", { pct: "80" })]
          ]}
        />
        <SearchField
          value={searchValue}
          onValueChange={onSearchChange}
          label={t("encounters.searchPlaceholder")}
          placeholder={t("encounters.searchPlaceholder")}
          containerClassName={styles.filterSearch}
        />
        <FilterSelect
          label={t("common.sortBy")}
          value={filters.sort}
          onValueChange={(value) => onPatch({ sort: value as EncounterFilterState["sort"] })}
          items={[
            ["date", t("encounters.filter.sortDate")],
            ["closeness", t("encounters.filter.sortCloseness")],
            ["upcoming", t("encounters.filter.sortUpcoming")]
          ]}
          triggerLabel={t("encounters.filter.sortTrigger", {
            label: t(`encounters.sort.${filters.sort}`)
          })}
          className={styles.filterSelectSort}
        />
      </div>
    </section>
  );
}

function FilterSelect({
  label,
  value,
  onValueChange,
  items,
  triggerLabel,
  className
}: Readonly<{
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  items: [string, string][];
  triggerLabel?: string;
  className?: string;
}>) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger className={cn(styles.filterSelectTrigger, className)} aria-label={label}>
        {triggerLabel ? <span>{triggerLabel}</span> : <SelectValue />}
      </SelectTrigger>
      <SelectContent>
        {items.map(([itemValue, itemLabel]) => (
          <SelectItem key={itemValue} value={itemValue}>
            {itemLabel}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
