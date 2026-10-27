"use client";

import { useTranslations } from "next-intl";
import { ChartColumn, List, X } from "lucide-react";

import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SearchField } from "@/components/ui/search-field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { GameFilterHint } from "@/components/workspace/GameFilterHint";
import type { EncounterOverview } from "@/types/encounter.types";
import type { LookupItem } from "@/types/pagination.types";

import {
  CLOSENESS_STEPS,
  DEFAULT_FILTERS,
  formatPercent,
  QUICK_FILTERS,
  type EncounterFilterState,
  type EncounterStatus,
  type EncountersView
} from "./encounters.helpers";
import { EncountersPresets } from "./EncountersPresets";
import type { EncountersFilterControls } from "./useEncountersFilters";

const SEGMENTS = [
  { value: "all", label: "encounters.toolbar.status.all" },
  { value: "live", label: "encounters.toolbar.status.live" },
  { value: "upcoming", label: "encounters.toolbar.status.upcoming" },
  { value: "completed", label: "encounters.toolbar.status.completed" }
] as const satisfies readonly { value: EncounterStatus | "all"; label: string }[];

const BEST_OF = [3, 5, 7];

/** «Напряжённость от 60 %» or, for a histogram bucket, «Напряжённость 40–50 %»: the select and its chip agree. */
function useClosenessLabel() {
  const t = useTranslations();
  const format = useFormatter();
  return (min: number | null, max: number | null) =>
    max == null
      ? t("encounters.toolbar.closenessMin", { pct: formatPercent(format, min ?? 0) })
      : t("encounters.toolbar.closenessRange", { from: formatPercent(format, min ?? 0), to: formatPercent(format, max) });
}

/** Phones get 40px targets; from `md` the row is the shared 32px toolbar height. */
const TOUCH = "max-md:h-10";

/**
 * The one toolbar: status segments with the filtered overview's counts, the scoping selects (the tournament
 * picker is one game's, so under every game the scope hint stands in for it), search, sort, «Подборки» and the
 * list/summary switch. Sticky under the site header from `md` up; on a phone it would eat half the viewport.
 *
 * From `md` it is two rows: what is shown (segments … presets, view) over how it is narrowed (selects … search,
 * sort). On a phone the same controls stack as one grid column, the last row holding sort, presets and the view
 * toggle; the row wrappers dissolve (`contents`) there and `order` places them.
 */
export function EncountersToolbar({
  controls,
  counts,
  tournaments,
  gameBound
}: Readonly<{
  controls: EncountersFilterControls;
  /** The overview under the current filters; `undefined` while it loads. */
  counts: EncounterOverview["counts"] | undefined;
  tournaments: LookupItem[];
  /** The page reads one game: its game-bound filters are offered; else the hint is. */
  gameBound: boolean;
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const closenessLabel = useClosenessLabel();
  const { filters, patchFilters } = controls;
  const upcoming = filters.status === "upcoming";
  // A select value is "min:max", either side empty when unbounded.
  const closenessValue =
    filters.closeness_min == null && filters.closeness_max == null
      ? "all"
      : `${filters.closeness_min ?? ""}:${filters.closeness_max ?? ""}`;
  // A bound the select does not offer (a histogram bucket, an old link) is still shown as what it is.
  const closenessItems: string[] = CLOSENESS_STEPS.map((step) => `${step}:`);
  if (closenessValue !== "all" && !closenessItems.includes(closenessValue)) closenessItems.push(closenessValue);
  const bestOfItems =
    filters.best_of != null && !BEST_OF.includes(filters.best_of) ? [...BEST_OF, filters.best_of] : BEST_OF;

  return (
    <div className="z-30 -mx-4 bg-[color:var(--aqt-bg)]/95 px-4 py-2 backdrop-blur md:sticky md:top-[var(--aqt-header-h)] md:-mx-6 md:px-6 xl:-mx-10 xl:px-10">
      <Card asChild>
        <section
          aria-label={t("encounters.toolbar.label")}
          className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-2 p-2.5 md:flex md:flex-col md:items-stretch"
        >
          <div className="contents md:flex md:flex-wrap md:items-center md:gap-2">
            {/* Phone: one horizontally scrollable row rather than segments wrapping under each other. */}
            <div className="-mx-2.5 min-w-0 overflow-x-auto px-2.5 [scrollbar-width:none] max-md:order-1 max-md:col-span-3 [&::-webkit-scrollbar]:hidden md:mx-0 md:overflow-visible md:px-0">
              <ToggleGroup
                variant="pill"
                size="sm"
                value={filters.status ?? "all"}
                onValueChange={(value) => patchFilters({ status: value === "all" ? null : (value as EncounterStatus) })}
                aria-label={t("common.status")}
                className="w-max"
              >
                {SEGMENTS.map((segment) => {
                  const count = counts?.[segment.value];
                  return (
                    <ToggleGroupItem key={segment.value} value={segment.value} className={`group gap-1.5 ${TOUCH}`}>
                      {t(segment.label)}
                      {count == null ? null : (
                        <span className="tabular-nums text-[color:var(--aqt-fg-faint)] group-data-[state=on]:text-current">
                          {format.number(count)}
                        </span>
                      )}
                    </ToggleGroupItem>
                  );
                })}
              </ToggleGroup>
            </div>
            <EncountersPresets
              controls={controls}
              counts={counts}
              triggerClassName={`${TOUCH} max-md:order-6 md:ml-auto`}
            />
            {/* A phone row of its own with «Подборки»: room for the labels. */}
            <div className="max-md:order-7 max-md:col-span-2">
              <ToggleGroup
                variant="pill"
                size="sm"
                value={controls.view}
                onValueChange={(value) => controls.setView(value as EncountersView)}
                aria-label={t("encounters.toolbar.view.label")}
              >
                <ToggleGroupItem value="list" className={`gap-1.5 ${TOUCH}`}>
                  <List aria-hidden width={14} height={14} />
                  <span>{t("encounters.toolbar.view.list")}</span>
                </ToggleGroupItem>
                <ToggleGroupItem value="insights" className={`gap-1.5 ${TOUCH}`}>
                  <ChartColumn aria-hidden width={14} height={14} />
                  <span>{t("encounters.toolbar.view.insights")}</span>
                </ToggleGroupItem>
              </ToggleGroup>
            </div>
          </div>

          <div className="contents md:flex md:flex-wrap md:items-center md:gap-2">
            {gameBound ? (
              <FilterSelect
                label={t("common.tournament")}
                value={filters.tournament_id == null ? "all" : String(filters.tournament_id)}
                onValueChange={(value) => patchFilters({ tournament_id: value === "all" ? null : Number(value) })}
                items={[
                  ["all", t("encounters.toolbar.tournamentAny")],
                  ...tournaments.map((item): [string, string] => [String(item.id), item.name])
                ]}
                className="max-md:order-2 max-md:col-span-3"
              />
            ) : (
              <GameFilterHint className={`shrink-0 max-md:order-2 max-md:col-span-3 ${TOUCH}`} />
            )}
            {/* Two equal columns on a phone; at `md` the wrapper dissolves into the row. */}
            <div className="grid grid-cols-2 gap-2 max-md:order-3 max-md:col-span-3 md:contents">
              <FilterSelect
                label={t("encounters.toolbar.format")}
                value={filters.best_of == null ? "all" : String(filters.best_of)}
                onValueChange={(value) => patchFilters({ best_of: value === "all" ? null : Number(value) })}
                items={[
                  ["all", t("encounters.toolbar.formatAny")],
                  ...bestOfItems.map((count): [string, string] => [
                    String(count),
                    t("encounters.toolbar.formatValue", { count })
                  ])
                ]}
              />
              <FilterSelect
                label={t("encounters.toolbar.closeness")}
                value={closenessValue}
                onValueChange={(value) => {
                  const [min, max] = value === "all" ? ["", ""] : value.split(":");
                  patchFilters({ closeness_min: min ? Number(min) : null, closeness_max: max ? Number(max) : null });
                }}
                items={[
                  ["all", t("encounters.toolbar.closenessAny")],
                  ...closenessItems.map((key): [string, string] => {
                    const [min, max] = key.split(":");
                    return [key, closenessLabel(min ? Number(min) : null, max ? Number(max) : null)];
                  })
                ]}
              />
            </div>
            <SearchField
              value={controls.searchValue}
              onValueChange={controls.setSearchValue}
              label={t("encounters.toolbar.searchLabel")}
              placeholder={t("encounters.toolbar.searchPlaceholder")}
              containerClassName="max-md:order-4 max-md:col-span-3 md:ml-auto md:min-w-[10rem] md:max-w-sm md:flex-1"
              className={TOUCH}
            />
            {/* «Предстоят» always reads soonest first: the select says so instead of offering an order it ignores. */}
            <FilterSelect
              label={t("common.sortBy")}
              value={upcoming ? "soonest" : filters.sort}
              disabled={upcoming}
              onValueChange={(value) => patchFilters({ sort: value as EncounterFilterState["sort"] })}
              items={
                upcoming
                  ? [["soonest", t("encounters.toolbar.sort.soonest")]]
                  : [
                      ["date", t("encounters.toolbar.sort.date")],
                      ["closeness", t("encounters.toolbar.sort.closeness")]
                    ]
              }
              className="max-md:order-5 max-md:col-span-3"
            />
          </div>
        </section>
      </Card>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onValueChange,
  items,
  disabled,
  className
}: Readonly<{
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  items: [string, string][];
  disabled?: boolean;
  className?: string;
}>) {
  return (
    <Select value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectTrigger
        size="sm"
        variant="surface"
        // A phone's grid cell sets the width; from `md` the trigger takes its label's.
        className={cn("gap-1.5 md:w-auto md:max-w-[220px] md:flex-none", TOUCH, className)}
        aria-label={label}
      >
        {/* Unset, a filter names its dimension ("Формат"); the list's first item still reads "Любой формат". */}
        {value === "all" ? <SelectValue>{label}</SelectValue> : <SelectValue />}
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

/**
 * One removable chip per filter in effect (status aside: the segments show it) and «Сбросить», which keeps the
 * status and the order. Nothing renders while nothing narrows.
 */
export function EncountersActiveFilters({
  controls,
  tournaments
}: Readonly<{ controls: EncountersFilterControls; tournaments: LookupItem[] }>) {
  const t = useTranslations();
  const closenessLabel = useClosenessLabel();
  // What the reads use: the settled term, and under every game no tournament/stage.
  const active = controls.effectiveFilters;
  const clear = (patch: Partial<EncounterFilterState>) =>
    controls.applyFilters({ ...controls.filters, query: active.query, ...patch });
  const chips: { key: string; label: string; patch: Partial<EncounterFilterState> }[] = [];

  if (active.tournament_id != null) {
    const name = tournaments.find((item) => item.id === active.tournament_id)?.name ?? `#${active.tournament_id}`;
    chips.push({ key: "tournament", label: t("encounters.chips.tournament", { name }), patch: { tournament_id: null } });
  }
  if (active.stage_id != null || active.stage_item_id != null) {
    chips.push({ key: "stage", label: t("encounters.chips.stage"), patch: { stage_id: null, stage_item_id: null } });
  }
  if (active.best_of != null) {
    chips.push({
      key: "best_of",
      label: t("encounters.toolbar.formatValue", { count: active.best_of }),
      patch: { best_of: null }
    });
  }
  if (active.closeness_min != null || active.closeness_max != null) {
    chips.push({
      key: "closeness",
      label: closenessLabel(active.closeness_min, active.closeness_max),
      patch: { closeness_min: null, closeness_max: null }
    });
  }
  if (active.query) {
    chips.push({ key: "query", label: t("encounters.chips.search", { query: active.query }), patch: { query: "" } });
  }
  for (const quick of QUICK_FILTERS) {
    if (quick.isOn(active)) chips.push({ key: quick.id, label: t(quick.label), patch: quick.patch(false) });
  }
  if (!chips.length) return null;

  return (
    <div role="group" aria-label={t("encounters.chips.label")} className="flex flex-wrap items-center gap-2">
      {chips.map((chip) => (
        <Button
          key={chip.key}
          variant="accent"
          size="sm"
          className={`gap-1.5 ${TOUCH}`}
          aria-label={t("encounters.chips.remove", { label: chip.label })}
          onClick={() => clear(chip.patch)}
        >
          {chip.label}
          <X aria-hidden />
        </Button>
      ))}
      <Button
        variant="ghost"
        size="sm"
        className={TOUCH}
        onClick={() =>
          controls.applyFilters({ ...DEFAULT_FILTERS, status: active.status, sort: active.sort })
        }
      >
        {t("common.reset")}
      </Button>
    </div>
  );
}
