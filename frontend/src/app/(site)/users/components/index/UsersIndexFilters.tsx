"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, Search } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionLabel, getDivisionOptions } from "@/lib/divisions/grid";
import { cn } from "@/lib/utils";
import type { UserOverviewStats } from "@/types/user.types";

import { ROLE_FILTERS, SORT_OPTIONS, type SortValue } from "./users-index.model";
import type { UsersIndexParamControls } from "./useUsersIndexParams";
import styles from "./Users.module.css";

/** Role chips, the division range, search and (analytics only) the sort menu. */
export function UsersIndexFilters({
  controls,
  stats
}: Readonly<{
  controls: UsersIndexParamControls;
  stats: UserOverviewStats | undefined;
}>) {
  const t = useTranslations();
  const divisionGrid = useDivisionGrid();
  const divisionOptions = getDivisionOptions(divisionGrid);
  const { role, divMin, divMax, sort, order, view } = controls.params;
  const sortLabel = t(
    SORT_OPTIONS.find((option) => option.value === sort)?.labelKey ?? "users.list.sort.name"
  );

  return (
    <section>
      <div className={styles.filters}>
        {ROLE_FILTERS.map((option) => {
          let count: number | undefined;
          if (stats) {
            if (option.value === "all") count = stats.total_players;
            else if (option.value === "Tank") count = stats.tank_count;
            else if (option.value === "Damage") count = stats.damage_count;
            else if (option.value === "Support") count = stats.support_count;
          }
          return (
            <FilterChip
              key={option.value}
              active={(role ?? "all") === option.value}
              count={count}
              onClick={() => controls.setRole(option.value)}
            >
              {t(option.labelKey)}
            </FilterChip>
          );
        })}

        {stats && stats.flex_count > 0 ? (
          <FilterChip count={stats.flex_count}>{t("common.roles.flex")}</FilterChip>
        ) : null}

        <span className={styles.filterDivider} />

        <DivisionBoundMenu
          label={t("users.list.filters.divMin", {
            value:
              divMin != null
                ? (getDivisionLabel(divisionGrid, divMin) ?? t("common.any"))
                : t("common.any")
          })}
          menuLabel={t("users.list.filters.minDivision")}
          idPrefix="min"
          value={divMin}
          options={divisionOptions}
          onChange={controls.setDivMin}
        />

        <DivisionBoundMenu
          label={t("users.list.filters.divMax", {
            value:
              divMax != null
                ? (getDivisionLabel(divisionGrid, divMax) ?? t("common.any"))
                : t("common.any")
          })}
          menuLabel={t("users.list.filters.maxDivision")}
          idPrefix="max"
          value={divMax}
          options={divisionOptions}
          onChange={controls.setDivMax}
        />

        <div className={styles.filterSearch}>
          <Search size={14} className={styles.filterSearchIcon} aria-hidden />
          <input
            type="search"
            value={controls.searchInput}
            onChange={(event) => controls.setSearchInput(event.target.value)}
            placeholder={t("users.list.filters.searchPlaceholder")}
            aria-label={t("users.list.a11y.searchPlayers")}
          />
        </div>

        {view === "analytics" ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button type="button" className={cn(styles.filterChip, styles.filterSort)}>
                <span>
                  {t("users.list.filters.sortValue", {
                    value: `${sortLabel} ${order === "desc" ? "▾" : "▴"}`
                  })}
                </span>
                <ChevronDown size={10} aria-hidden />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>{t("common.sortBy")}</DropdownMenuLabel>
              <DropdownMenuRadioGroup
                value={sort}
                onValueChange={(value) => controls.setSort(value as SortValue)}
              >
                {SORT_OPTIONS.map((option) => (
                  <DropdownMenuRadioItem key={option.value} value={option.value}>
                    {t(option.labelKey)}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
              <DropdownMenuSeparator />
              <DropdownMenuLabel>{t("common.order")}</DropdownMenuLabel>
              <DropdownMenuCheckboxItem
                checked={order === "asc"}
                onCheckedChange={() => controls.setOrder("asc")}
              >
                {t("common.ascending")}
              </DropdownMenuCheckboxItem>
              <DropdownMenuCheckboxItem
                checked={order === "desc"}
                onCheckedChange={() => controls.setOrder("desc")}
              >
                {t("common.descending")}
              </DropdownMenuCheckboxItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>
    </section>
  );
}

/** One end of the division range — the two menus differ only in their copy. */
function DivisionBoundMenu({
  label,
  menuLabel,
  idPrefix,
  value,
  options,
  onChange
}: Readonly<{
  label: string;
  menuLabel: string;
  idPrefix: string;
  value: number | undefined;
  options: number[];
  onChange: (value: string) => void;
}>) {
  const t = useTranslations();
  const divisionGrid = useDivisionGrid();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(styles.filterChip, value != null && styles.filterChipActive)}
        >
          <span>{label}</span>
          <ChevronDown size={10} aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto">
        <DropdownMenuLabel>{menuLabel}</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={value != null ? String(value) : "all"} onValueChange={onChange}>
          <DropdownMenuRadioItem value="all">
            {t("users.list.filters.allDivisions")}
          </DropdownMenuRadioItem>
          {options.map((division) => (
            <DropdownMenuRadioItem key={`${idPrefix}-${division}`} value={String(division)}>
              {getDivisionLabel(divisionGrid, division)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function FilterChip({
  active = false,
  count,
  onClick,
  children
}: Readonly<{
  active?: boolean;
  count?: number;
  onClick?: () => void;
  children: ReactNode;
}>) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(styles.filterChip, active && styles.filterChipActive)}
    >
      <span>{children}</span>
      {typeof count === "number" ? <span className={styles.filterChipCount}>{count}</span> : null}
    </button>
  );
}
