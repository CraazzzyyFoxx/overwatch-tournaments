"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ChevronLeft, ListFilter, Plus, X } from "lucide-react";
import { useDebounce } from "use-debounce";

import { Button } from "@/components/ui/button";
import { Combobox, ComboboxCheck, ComboboxMeta } from "@/components/ui/combobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { FilterChip } from "@/components/ui/filter-chip";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useTableToolbarNarrow } from "@/components/data-table/toolbar-context";
import {
  isFilterActive,
  type FilterState,
  type FilterDef,
  type FilterOption,
  type FilterValue
} from "@/components/kit/useFilters";

export interface FilterBarProps {
  defs: FilterDef[];
  filters: FilterState;
  /**
   * Filter controls that are not a `FilterDef` — a range picker, a "pending"
   * shortcut — drawn with the inline selects. Never a command: those are the
   * table's `commands`.
   */
  extraFilters?: ReactNode;
}

/** One active chip: which filter, which value, and how to drop it. */
interface ActiveChip {
  id: string;
  label: string;
  onRemove: () => void;
}

function optionLabel(def: FilterDef, value: string): string {
  if (def.kind === "single" || def.kind === "multi") {
    return def.options.find((option) => option.value === value)?.label ?? value;
  }
  return value;
}

/** The "no value" item of an inline select: Radix forbids an empty item value. */
const INLINE_ALL = "__all__";

type InlineDef = Extract<FilterDef, { kind: "single" }> & { inline: { allLabel: string } };

/**
 * The one filter surface for the admin panel: removable chips + a "+ Filter"
 * popover holding everything not yet applied.
 *
 * It replaced both earlier conventions at once — a "Filter by tournament"
 * `<Select>` in the table toolbar and the per-column funnel popovers — so a
 * screen has exactly one place where "narrow this list" lives, and that place
 * writes the URL.
 *
 * In a narrow table toolbar its pieces become the toolbar row's own items:
 * the picker shrinks to an icon with the active count beside the search, and
 * the chips, inline selects and extra filters take a row below, only while
 * there are any.
 */
export function FilterBar({
  defs,
  filters,
  extraFilters
}: Readonly<FilterBarProps>) {
  const t = useTranslations("kit.actions");
  const narrow = useTableToolbarNarrow();
  const [open, setOpen] = useState(false);
  const [pickerKey, setPickerKey] = useState<string | null>(null);
  /** The picker's search field, shared by both levels; reset whenever the level changes. */
  const [query, setQuery] = useState("");
  const [debouncedEntityQuery] = useDebounce(query, 250);
  const [entityResults, setEntityResults] = useState<FilterOption[]>([]);
  /**
   * Labels for entity values, learnt when the user picks one. The URL carries
   * only the id, so after a reload the chip falls back to showing that id
   * rather than inventing a name it has not been told.
   */
  const [entityLabels, setEntityLabels] = useState<Record<string, string>>({});

  /**
   * A filter is offered only when it is a choice: a toggle, a search, or a
   * list with two or more options. An option nobody holds is not offered.
   */
  const offered = defs
    .map((def) =>
      def.kind === "single" || def.kind === "multi"
        ? { ...def, options: def.options.filter((option) => option.count !== 0) }
        : def
    )
    .filter((def) => def.kind === "toggle" || def.kind === "entity" || def.options.length > 1);
  // An inline filter is its own select, so it is neither a chip nor a "+ Filter" entry.
  const inline = offered.filter(
    (def): def is InlineDef => def.kind === "single" && def.inline !== undefined
  );
  const inlineKeys = new Set(inline.map((def) => def.key));
  const available = offered.filter((def) => !inlineKeys.has(def.key));
  const picker = available.find((def) => def.key === pickerKey) ?? null;

  useEffect(() => {
    if (!picker || picker.kind !== "entity") return;
    let cancelled = false;
    void picker.search(debouncedEntityQuery).then((results) => {
      if (!cancelled) setEntityResults(results);
    });
    return () => {
      cancelled = true;
    };
  }, [picker, debouncedEntityQuery]);

  const openLevel = (key: string | null) => {
    setPickerKey(key);
    setQuery("");
  };

  const closePicker = () => {
    setOpen(false);
    openLevel(null);
    setEntityResults([]);
  };

  const write = (def: FilterDef, value: FilterValue | null) => {
    const dropped = def.resets?.(value) ?? [];
    if (dropped.length === 0) filters.set(def.key, value);
    else filters.setMany({ ...Object.fromEntries(dropped.map((key) => [key, null])), [def.key]: value });
  };

  // Every def, not only the offered ones: a value already in the URL must
  // stay removable even when its filter has no second option to offer.
  const chips: ActiveChip[] = [];
  for (const def of defs) {
    if (inlineKeys.has(def.key)) continue;
    const value = filters.values[def.key];
    if (!isFilterActive(value)) continue;

    if (Array.isArray(value)) {
      for (const item of value) {
        chips.push({
          id: `${def.key}:${item}`,
          label: `${def.label}: ${optionLabel(def, item)}`,
          onRemove: () =>
            write(
              def,
              value.filter((other) => other !== item)
            )
        });
      }
      continue;
    }

    const shown =
      value === true
        ? def.label
        : `${def.label}: ${
            def.kind === "entity"
              ? (entityLabels[`${def.key}:${value}`] ?? String(value))
              : optionLabel(def, String(value))
          }`;
    chips.push({ id: def.key, label: shown, onRemove: () => write(def, null) });
  }

  const selectOption = (def: FilterDef, option: FilterOption) => {
    if (def.kind === "multi") {
      // The picker stays open: every option shows whether it is on, and a
      // click flips just that one.
      const current = filters.values[def.key];
      const list = Array.isArray(current) ? current : [];
      write(
        def,
        list.includes(option.value)
          ? list.filter((value) => value !== option.value)
          : [...list, option.value]
      );
      return;
    }
    if (def.kind === "entity") {
      setEntityLabels((previous) => ({
        ...previous,
        [`${def.key}:${option.value}`]: option.label
      }));
    }
    write(def, option.value);
    closePicker();
  };

  const pickerValue = picker ? filters.values[picker.key] : undefined;
  const isPicked = (option: FilterOption) =>
    Array.isArray(pickerValue) ? pickerValue.includes(option.value) : pickerValue === option.value;

  /** Options for the second popover level. A `toggle` never reaches it. */
  const pickerOptions: FilterOption[] =
    picker === null || picker.kind === "toggle"
      ? []
      : picker.kind === "entity"
        ? entityResults
        : picker.options;

  const inlineSelects = inline.map((def) => {
    const value = filters.values[def.key];
    return (
      <Select
        key={def.key}
        value={typeof value === "string" && value !== "" ? value : INLINE_ALL}
        onValueChange={(next) => write(def, next === INLINE_ALL ? null : next)}
      >
        <SelectTrigger size="sm" aria-label={def.label} className="w-auto min-w-36 gap-2">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={INLINE_ALL}>{def.inline.allLabel}</SelectItem>
          {def.options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              <span className="flex items-center gap-2">
                {option.icon}
                {option.label}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  });

  const chipButtons = chips.map((chip) => (
    <FilterChip
      key={chip.id}
      active
      aria-label={t("removeFilter", { label: chip.label })}
      onClick={chip.onRemove}
    >
      {chip.label}
      <X aria-hidden className="size-3" />
    </FilterChip>
  ));

  const pickerPopover =
    available.length > 0 ? (
      <Combobox
        open={open}
        onOpenChange={(next) => (next ? setOpen(true) : closePicker())}
        trigger={
          // A menu trigger, not a toggle: drop the chip's `aria-pressed`.
          narrow ? (
            // The chips sit on a row of their own here; the count says they are there.
            <FilterChip aria-label={t("addFilter")} aria-pressed={undefined} count={chips.length > 0 ? chips.length : undefined}>
              <ListFilter aria-hidden className="size-3.5" />
            </FilterChip>
          ) : (
            <FilterChip aria-label={t("addFilter")} aria-pressed={undefined}>
              <Plus aria-hidden className="size-3" />
              {t("filter")}
            </FilterChip>
          )
        }
        header={
          picker === null ? null : (
            <div className="flex items-center gap-1 border-b border-border/60 px-2 py-1.5">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                onClick={() => openLevel(null)}
                aria-label={t("backToFilterList")}
                className="text-muted-foreground"
              >
                <ChevronLeft aria-hidden />
              </Button>
              <span className="text-xs font-medium text-foreground">{picker.label}</span>
            </div>
          )
        }
        searchValue={query}
        onSearchValueChange={setQuery}
        searchPlaceholder={
          picker === null ? t("filterBy") : t("searchPicker", { label: picker.label.toLowerCase() })
        }
        emptyMessage={picker === null ? t("noFilters") : t("nothingMatchesShort")}
        shouldFilter={picker?.kind !== "entity"}
      >
        <CommandGroup>
          {picker === null
            ? available.map((def) => (
                <CommandItem
                  key={def.key}
                  value={def.label}
                  onSelect={() => {
                    if (def.kind === "toggle") {
                      write(def, true);
                      closePicker();
                      return;
                    }
                    openLevel(def.key);
                  }}
                >
                  {def.label}
                </CommandItem>
              ))
            : pickerOptions.map((option) => (
                <CommandItem
                  key={option.value}
                  value={option.label}
                  onSelect={() => selectOption(picker, option)}
                >
                  {option.icon}
                  <span className="min-w-0 flex-1 truncate">{option.label}</span>
                  {option.count !== undefined ? <ComboboxMeta>{option.count}</ComboboxMeta> : null}
                  <ComboboxCheck selected={isPicked(option)} />
                </CommandItem>
              ))}
        </CommandGroup>
      </Combobox>
    ) : null;

  const clearAll =
    chips.length > 1 ? (
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={filters.clear}
        className="text-muted-foreground"
      >
        {t("clearAll")}
      </Button>
    ) : null;

  if (narrow) {
    const hasRow = inline.length > 0 || Boolean(extraFilters) || chips.length > 0;
    return (
      // `contents`: the picker is the toolbar row's item, beside the search; the rest is its last row.
      <div className="contents">
        {pickerPopover}
        {hasRow ? (
          <div className="order-last flex basis-full flex-wrap items-center gap-2">
            {inlineSelects}
            {extraFilters}
            {chips.length > 0 ? (
              <div role="group" aria-label={t("activeFilters")} className="flex flex-wrap items-center gap-2">
                {chipButtons}
                {clearAll}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {inlineSelects}
      {extraFilters}
      <div role="group" aria-label={t("activeFilters")} className="flex flex-wrap items-center gap-2">
        {chipButtons}
        {pickerPopover}
        {clearAll}
      </div>
    </div>
  );
}
