"use client";

import { useId, useMemo, useState, type ReactNode } from "react";
import Image from "@/components/ui/image";
import { useTranslations } from "next-intl";
import { Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Combobox, ComboboxCheck } from "@/components/ui/combobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { PickBanKind } from "@/types/tournament.types";
import { matchesItemName } from "@/lib/tournament/pick-ban-config";
import { EmptyNote } from "@/components/kit/EmptyNote";

/** One selectable map or hero, flattened so both catalogues share one picker. */
export interface CatalogueItem {
  id: number;
  name: string;
  /** Game mode for a map, role for a hero. Disambiguates similar names. */
  group: string | null;
  imageSrc: string | null;
  /** A mode beside the maps: it narrows which logs a match accepts, and only a shared pool may name it. */
  isMode?: boolean;
}

/** Filter value showing every catalogue row regardless of its group. */
const ALL_GROUPS = "__all__";
/** Bucket for rows with no group, e.g. a map missing its gamemode relation. */
const UNGROUPED_GROUP = "__ungrouped__";

interface CatalogueGroup {
  key: string;
  /** Null only for the ungrouped bucket. */
  label: string | null;
  count: number;
}

/** Every group present in `options`, sorted by name with ungrouped last. */
function groupCatalogue(options: CatalogueItem[]): CatalogueGroup[] {
  const byKey = new Map<string, CatalogueGroup>();
  for (const option of options) {
    const key = option.group ?? UNGROUPED_GROUP;
    const existing = byKey.get(key);
    if (existing) existing.count += 1;
    else byKey.set(key, { key, label: option.group, count: 1 });
  }
  return [...byKey.values()].sort((left, right) => {
    if (left.label === null) return 1;
    if (right.label === null) return -1;
    return left.label.localeCompare(right.label);
  });
}

/**
 * Popover open state plus group/search filtering.
 *
 * Both selection modes filter the same catalogue by group then by name, and
 * both reset back to "everything" once the popover closes so reopening starts
 * fresh rather than on the last search.
 */
function useCatalogueFilter(options: CatalogueItem[]) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState(ALL_GROUPS);

  const groups = useMemo(() => groupCatalogue(options), [options]);
  const inGroup = useMemo(
    () =>
      groupFilter === ALL_GROUPS
        ? options
        : options.filter((option) => (option.group ?? UNGROUPED_GROUP) === groupFilter),
    [options, groupFilter]
  );
  // `matchesItemName` is the same fold the veto room's search uses, so a query
  // spelled the way a paper regulation spells it lands the same map everywhere.
  const visibleOptions = useMemo(
    () => inGroup.filter((option) => matchesItemName(option.name, query)),
    [inGroup, query]
  );

  return {
    open,
    setOpen,
    onOpenChange: (next: boolean) => {
      setOpen(next);
      if (!next) {
        setQuery("");
        setGroupFilter(ALL_GROUPS);
      }
    },
    query,
    setQuery,
    groupFilter,
    setGroupFilter,
    groups,
    visibleOptions
  };
}

/**
 * The group filter row above the search field: game mode for a map, role for a
 * hero. Hidden with nothing to narrow: a single-group catalogue (or one still
 * loading) has no use for a row of one redundant "All" chip.
 */
function GroupFilterRow({
  groups,
  value,
  onChange
}: Readonly<{
  groups: CatalogueGroup[];
  value: string;
  onChange: (value: string) => void;
}>) {
  const t = useTranslations("pickBan.admin");
  if (groups.length <= 1) return null;

  return (
    <FilterChipGroup label={t("groupFilterLabel")} className="border-b border-border p-1.5">
      <FilterChip active={value === ALL_GROUPS} onClick={() => onChange(ALL_GROUPS)}>
        {t("groupFilterAll")}
      </FilterChip>
      {groups.map((group) => (
        <FilterChip
          key={group.key}
          active={value === group.key}
          count={group.count}
          onClick={() => onChange(group.key)}
        >
          {group.label ?? t("groupFilterUngrouped")}
        </FilterChip>
      ))}
    </FilterChipGroup>
  );
}

/** Item art behind a flat scrim, so a label stays legible whatever the image. */
function ItemArt({ option }: Readonly<{ option: CatalogueItem }>) {
  return (
    <>
      {option.imageSrc ? (
        <span
          aria-hidden
          className="absolute inset-0 bg-cover bg-center opacity-35"
          style={{ backgroundImage: `url("${option.imageSrc}")` }}
        />
      ) : (
        <span aria-hidden className="absolute inset-0 bg-muted/40" />
      )}
      <span aria-hidden className="absolute inset-0 bg-background/60" />
    </>
  );
}

/**
 * One catalogue tile: art and name. The group is the filter row above, and the
 * pick order is the numbered chip list under the picker, so neither is
 * repeated on the tile.
 */
function CatalogueTile({
  option,
  selected,
  disabled,
  onToggle
}: Readonly<{
  option: CatalogueItem;
  selected: boolean;
  disabled: boolean;
  onToggle: () => void;
}>) {
  return (
    <Button
      type="button"
      variant="outline"
      aria-pressed={selected}
      aria-label={option.name}
      disabled={disabled}
      onClick={onToggle}
      className="relative h-20 flex-col items-stretch justify-end overflow-hidden rounded-lg p-2 text-left hover:border-primary/50 aria-pressed:border-primary"
    >
      <ItemArt option={option} />
      <span className="relative z-10 truncate text-xs font-semibold text-foreground">
        {option.name}
      </span>
    </Button>
  );
}

export interface CatalogueChipsProps {
  itemIds: number[];
  catalogue: Map<number, CatalogueItem>;
  disabled?: boolean;
  onRemove: (itemId: number) => void;
  /**
   * The row's first item, normally the picker trigger — it flows in the same
   * wrapping row as the chips rather than sitting above or below them. It leads
   * the row rather than trailing it so that adding a chip never moves it, which
   * would drag the anchored picker popover along with it.
   */
  leading?: ReactNode;
}

/** Selected items in stored order; each chip removes its item. */
export function CatalogueChips({
  itemIds,
  catalogue,
  disabled = false,
  onRemove,
  leading
}: Readonly<CatalogueChipsProps>) {
  const t = useTranslations("pickBan.admin");

  return (
    <ul className="flex flex-wrap items-center gap-1.5">
      {leading ? <li>{leading}</li> : null}
      {itemIds.map((itemId, index) => {
        const item = catalogue.get(itemId);
        const name = item?.name ?? `#${itemId}`;
        const content = (
          <>
            {item?.imageSrc ? (
              <Image
                src={item.imageSrc}
                alt=""
                width={16}
                height={16}
                className="size-4 shrink-0 rounded-sm object-cover"
              />
            ) : null}
            <span className="text-muted-foreground tabular-nums">{index + 1}</span>
            <span className="max-w-40 truncate">{name}</span>
          </>
        );
        return (
          <li key={itemId}>
            {disabled ? (
              <span className="flex items-center gap-1.5 text-xs">{content}</span>
            ) : (
              <FilterChip
                active
                aria-label={t("poolRemove", { item: name })}
                title={t("poolRemove", { item: name })}
                onClick={() => onRemove(itemId)}
              >
                {content}
                <X aria-hidden className="size-3.5" />
              </FilterChip>
            )}
          </li>
        );
      })}
    </ul>
  );
}

interface CataloguePickerBase {
  /** Decides the wording: a map catalogue and a hero catalogue read alike. */
  kind: PickBanKind;
  options: CatalogueItem[];
  disabled?: boolean;
}

export type CataloguePickerProps = CataloguePickerMulti | CataloguePickerSingle;

interface CataloguePickerMulti extends CataloguePickerBase {
  mode: "multi";
  selectedIds: number[];
  onToggle: (itemId: number) => void;
  /** Every item the filter and search currently show. */
  onSelectVisible: (itemIds: number[]) => void;
  onClearVisible: (itemIds: number[]) => void;
}

interface CataloguePickerSingle extends CataloguePickerBase {
  mode: "single";
  value: number | null;
  /** Accessible name of a trigger that shows only its value. */
  triggerLabel: string;
  /** Muted lead-in inside the trigger, e.g. "Reserve:". */
  triggerPrefix: string;
  onChange: (itemId: number | null) => void;
}

/**
 * The one catalogue surface of the pre-game editor.
 *
 * `multi` builds a pool (or a round group), `single` names a reserve. Both were
 * separate components with twelve label props each, one filter hook and one
 * tile renderer copied between them; the wording is derived from `kind` here
 * instead, so a map and a hero read identically wherever they are offered.
 *
 * A cmdk list read the catalogue as names alone; a map a captain bans
 * sight-unseen deserves to be recognized by its art first, which is why the
 * multi mode is a grid of tiles rather than a list.
 */
export function CataloguePicker(props: Readonly<CataloguePickerProps>) {
  const t = useTranslations("pickBan.admin");
  const { kind, options, disabled = false } = props;
  const searchId = useId();
  const filter = useCatalogueFilter(options);
  const searchPlaceholder = kind === "hero" ? t("searchHeroes") : t("searchMaps");

  if (props.mode === "single") {
    const selected = options.find((option) => option.id === props.value) ?? null;
    const choose = (itemId: number | null) => {
      props.onChange(itemId);
      filter.setOpen(false);
    };

    return (
      <Combobox
        open={filter.open}
        onOpenChange={filter.onOpenChange}
        label={
          selected && (
            <>
              <span className="text-muted-foreground">{props.triggerPrefix} </span>
              {selected.name}
            </>
          )
        }
        placeholder={`${props.triggerPrefix} ${t("slotReserveNone")}`}
        labelTitle={selected ? `${props.triggerPrefix} ${selected.name}` : undefined}
        triggerAriaLabel={props.triggerLabel}
        size="sm"
        triggerClassName="w-56 gap-2"
        disabled={disabled}
        header={
          <GroupFilterRow groups={filter.groups} value={filter.groupFilter} onChange={filter.setGroupFilter} />
        }
        searchValue={filter.query}
        onSearchValueChange={filter.setQuery}
        searchPlaceholder={searchPlaceholder}
        emptyMessage={t("catalogueEmpty")}
        shouldFilter={false}
        clear={{
          label: t("slotReserveNone"),
          value: t("slotReserveNone"),
          onSelect: () => choose(null),
          selected: props.value == null
        }}
      >
        <CommandGroup>
          {filter.visibleOptions.map((option) => (
            <CommandItem key={option.id} value={option.name} onSelect={() => choose(option.id)}>
              {option.imageSrc ? (
                <Image
                  src={option.imageSrc}
                  alt=""
                  width={24}
                  height={24}
                  className="size-6 shrink-0 rounded-sm object-cover outline outline-black/10 dark:outline-white/10"
                />
              ) : (
                <span aria-hidden className="size-6 shrink-0 rounded-sm bg-muted" />
              )}
              <span className="truncate">{option.name}</span>
              <span className="min-w-0 flex-1 truncate text-caption text-[color:var(--aqt-fg-dim)]">{option.group}</span>
              <ComboboxCheck selected={props.value === option.id} />
            </CommandItem>
          ))}
        </CommandGroup>
      </Combobox>
    );
  }

  const { selectedIds, onToggle, onSelectVisible, onClearVisible } = props;
  const selectionOrder = new Map(selectedIds.map((id, index) => [id, index]));
  const visibleIds = filter.visibleOptions.map((option) => option.id);
  const visibleSelectedCount = visibleIds.reduce(
    (total, id) => (selectionOrder.has(id) ? total + 1 : total),
    0
  );
  const addLabel = kind === "hero" ? t("poolAddHeroes") : t("poolAddMaps");

  return (
    <Popover open={filter.open} onOpenChange={filter.onOpenChange}>
      <PopoverTrigger asChild>
        <Button type="button" variant="dashed" size="sm" disabled={disabled}>
          <Plus aria-hidden className="size-4" />
          {addLabel}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-[min(40rem,calc(100vw-2rem))] p-3"
        // Selecting candidates is the whole point of this surface, so it stays
        // open across clicks; Escape and an outside click are the ways out.
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          document.getElementById(searchId)?.focus();
        }}
      >
        <div role="group" aria-label={addLabel} className="flex flex-col gap-3">
          <GroupFilterRow
            groups={filter.groups}
            value={filter.groupFilter}
            onChange={filter.setGroupFilter}
          />

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={searchId} className="text-xs font-medium text-muted-foreground">
              {t("pickerSearchLabel")}
            </Label>
            <Input
              id={searchId}
              value={filter.query}
              onChange={(event) => filter.setQuery(event.target.value)}
              placeholder={searchPlaceholder}
              size="sm"
            />
          </div>

          {filter.visibleOptions.length === 0 ? (
            <EmptyNote size="sm" className="text-center">
              {t("catalogueEmpty")}
            </EmptyNote>
          ) : (
            <div className="grid max-h-72 grid-cols-2 gap-2 overflow-y-auto sm:grid-cols-4">
              {filter.visibleOptions.map((option) => (
                <CatalogueTile
                  key={option.id}
                  option={option}
                  selected={selectionOrder.has(option.id)}
                  disabled={disabled}
                  onToggle={() => {
                    onToggle(option.id);
                    // A search finds one map; once it is picked, start the next search fresh.
                    filter.setQuery("");
                    document.getElementById(searchId)?.focus();
                  }}
                />
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={
                disabled || visibleIds.length === 0 || visibleSelectedCount === visibleIds.length
              }
              onClick={() => onSelectVisible(visibleIds)}
            >
              {t("poolSelectAllVisible")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={disabled || visibleSelectedCount === 0}
              onClick={() => onClearVisible(visibleIds)}
            >
              {t("poolClearVisible")}
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
