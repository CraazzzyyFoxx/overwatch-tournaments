"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { LayoutGrid, Table2 } from "lucide-react";

import { DivisionCombobox } from "@/components/DivisionCombobox";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";
import { GameFilterHint } from "@/components/workspace/GameFilterHint";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useRoleName } from "@/hooks/useRoleName";
import { registrationRoles, showsRoles, type RoleOntology } from "@/lib/roster/ontology";
import { OPEN_SLOT_CODE } from "@/lib/roster/shape";
import type { UserOverviewStats } from "@/types/user.types";

import { ThresholdPopover } from "@/app/(site)/users/components/shared/ThresholdPopover";

import { DEFAULT_MIN_ENCOUNTERS, MIN_ENCOUNTERS_OPTIONS, type ViewMode } from "./users-index.model";
import type { UsersIndexParamControls } from "./useUsersIndexParams";

interface RoleChip {
  /** The `?role=` value; `undefined` is "every player". */
  value: string | undefined;
  label: string;
  /** `undefined` while the stats read is in flight. */
  count: number | undefined;
}

/**
 * The one toolbar for both views: role chips and the division facet (the scope
 * hint under "all games"), the winrate sample floor, the logs switch, search and
 * the view toggle. Sticky under the site header from `md` up; on a phone it
 * would eat half the viewport.
 */
export function UsersIndexFilters({
  controls,
  stats,
  ontology,
  allGames,
  foundCount
}: Readonly<{
  controls: UsersIndexParamControls;
  stats: UserOverviewStats | undefined;
  /** The browsed game's role dictionary: its rated roles are the chips (none while it loads). */
  ontology: RoleOntology | null;
  /** "All games": the role chips and the division facet need a game, so the scope hint stands in for them. */
  allGames: boolean;
  /** `undefined` while loading, `null` when the list read failed. */
  foundCount: number | null | undefined;
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const nameOf = useRoleName();
  const { role, divisions, hasLogs, minEncounters, view } = controls.params;
  const roleChips: RoleChip[] = [
    { value: undefined, label: t("common.all"), count: stats?.total_players },
    ...registrationRoles(ontology).map((node) => ({
      value: node.code,
      label: nameOf(node),
      count: stats ? (stats.role_counts[node.code] ?? 0) : undefined
    })),
    { value: OPEN_SLOT_CODE, label: t("common.roles.flex"), count: stats?.flex_declared_count }
  ];

  const divisionCounts = useMemo(() => {
    const counts: Record<number, number> = {};
    for (const entry of stats?.division_counts ?? []) {
      counts[entry.division] = entry.count;
    }
    return counts;
  }, [stats?.division_counts]);

  // `min_encounters` is not a narrowing filter, but it is a setting the reader
  // changed, so the reset affordance has to acknowledge it.
  const showFoundLine =
    controls.hasActiveFilters || minEncounters !== DEFAULT_MIN_ENCOUNTERS;

  return (
    <div className="z-30 -mx-4 bg-[color:var(--aqt-bg)]/95 px-4 py-2 backdrop-blur md:sticky md:top-[var(--aqt-header-h)] md:-mx-6 md:px-6 xl:-mx-10 xl:px-10">
      <Card className="flex flex-col gap-2.5 p-2.5 md:flex-row md:flex-wrap md:items-center md:gap-2">
        {allGames ? (
          <GameFilterHint className="shrink-0" />
        ) : showsRoles(ontology) ? (
          <FilterChipGroup
            label={t("users.list.filters.roleGroup")}
            className="-mx-2.5 flex items-center gap-2 overflow-x-auto px-2.5 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden md:mx-0 md:flex-wrap md:overflow-visible md:px-0 md:pb-0"
          >
            {roleChips.map((chip) => (
              <FilterChip
                key={chip.value ?? "all"}
                active={role === chip.value}
                count={chip.count}
                onClick={() => controls.setRole(chip.value)}
                className="shrink-0"
              >
                {chip.label}
              </FilterChip>
            ))}
          </FilterChipGroup>
        ) : null}

        {/* One wrapping row of compact controls on a phone; at `md` the wrapper
            dissolves so they are direct children of the toolbar row again. */}
        <div className="flex flex-wrap items-center gap-2 md:contents">
          {allGames ? null : (
            <DivisionCombobox
              multiple
              values={divisions}
              onValuesChange={controls.setDivisions}
              grid={controls.divisionGrid}
              counts={divisionCounts}
              placeholder={t("users.list.filters.divisions")}
              ariaLabel={t("users.list.filters.divisions")}
              size="sm"
              triggerClassName="w-auto gap-2"
            />
          )}

          <ThresholdPopover
            label={t("users.list.filters.minEncounters")}
            hint={t("users.list.filters.minEncountersHint")}
            triggerLabel={t("users.list.filters.minEncountersValue", { value: String(minEncounters) })}
            value={minEncounters}
            options={MIN_ENCOUNTERS_OPTIONS}
            onChange={controls.setMinEncounters}
          />

          {/* A `<label>` cannot name a `<button role="switch">`, so the name is on
              the control and the visible copy is decorative. */}
          <span className="flex h-8 shrink-0 items-center gap-2 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3 text-label text-[color:var(--aqt-fg-muted)]">
            <Switch
              size="sm"
              checked={hasLogs}
              onCheckedChange={controls.setHasLogs}
              aria-label={t("users.list.filters.withLogs")}
            />
            <span aria-hidden>{t("users.list.filters.withLogs")}</span>
          </span>
        </div>

        {showFoundLine ? (
          <span className="flex shrink-0 items-center gap-3 px-1 text-label text-[color:var(--aqt-fg-faint)] md:ml-auto">
            {foundCount == null ? null : (
              <span className="tabular-nums">
                {t("users.list.filters.found", { count: format.number(foundCount) })}
              </span>
            )}
            <Button variant="link" size="inline" onClick={controls.resetFilters}>
              {t("users.list.filters.resetAll")}
            </Button>
          </span>
        ) : null}

        <SearchField
          value={controls.searchInput}
          onValueChange={controls.setSearchInput}
          label={t("users.list.filters.searchByName")}
          placeholder={t("users.list.filters.searchPlaceholder")}
          // The found/reset group, when shown, takes the push-right margin.
          containerClassName={`w-full md:w-auto md:min-w-[12rem] md:max-w-xs md:flex-1 ${showFoundLine ? "" : "md:ml-auto"}`}
          className="max-md:h-10"
        />

        <ToggleGroup
          variant="pill"
          size="sm"
          value={view}
          onValueChange={(next) => next && controls.setView(next as ViewMode)}
          aria-label={t("users.list.a11y.viewMode")}
          className="max-md:hidden"
        >
          <ToggleGroupItem value="table">
            <Table2 aria-hidden width={14} height={14} />
            <span className="sr-only">{t("users.list.view.table")}</span>
          </ToggleGroupItem>
          <ToggleGroupItem value="catalog">
            <LayoutGrid aria-hidden width={14} height={14} />
            <span className="sr-only">{t("users.list.view.catalog")}</span>
          </ToggleGroupItem>
        </ToggleGroup>
      </Card>
    </div>
  );
}
