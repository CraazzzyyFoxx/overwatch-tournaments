"use client";

import { useId, useMemo, useState, type ReactNode } from "react";
import Image from "next/image";
import { useTranslations } from "next-intl";
import { Check, ChevronsUpDown, Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { badgeVariants } from "@/components/ui/badge";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { PickBanKind } from "@/types/tournament.types";
import { matchesItemName } from "@/lib/pick-ban-config";
import { EmptyNote } from "@/components/kit/EmptyNote";

/** One selectable map or hero, flattened so both catalogues share one picker. */
export interface CatalogueItem {
  id: number;
  name: string;
  /** Game mode for a map, role for a hero. Disambiguates similar names. */
  group: string | null;
  imageSrc: string | null;
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
 * hero. Hidden with nothing to narrow — a single-group catalogue (or one still
 * loading) has no use for a row of one redundant "All" pill.
 */
function GroupFilterRow({
  groups,
  total,
  value,
  onChange
}: Readonly<{
  groups: CatalogueGroup[];
  total: number;
  value: string;
  onChange: (value: string) => void;
}>) {
  const t = useTranslations("pickBan.admin");
  if (groups.length <= 1) return null;

  return (
    <div
      role="group"
      aria-label={t("groupFilterLabel")}
      className="flex flex-wrap gap-1 border-b border-border p-1.5"
    >
      <Button
        type="button"
        size="sm"
        variant={value === ALL_GROUPS ? "default" : "outline"}
        aria-pressed={value === ALL_GROUPS}
        onClick={() => onChange(ALL_GROUPS)}
        className="h-6 px-2 text-[0.6875rem]"
      >
        {t("groupFilterAll")} ({total})
      </Button>
      {groups.map((group) => (
        <Button
          key={group.key}
          type="button"
          size="sm"
          variant={value === group.key ? "default" : "outline"}
          aria-pressed={value === group.key}
          onClick={() => onChange(group.key)}
          className="h-6 px-2 text-[0.6875rem]"
        >
          {group.label ?? t("groupFilterUngrouped")} ({group.count})
        </Button>
      ))}
    </div>
  );
}

/** Item art behind a scrim, so a label stays legible whatever the image. */
function ItemArt({ option }: Readonly<{ option: CatalogueItem }>) {
  return (
    <>
      {option.imageSrc ? (
        <span
          aria-hidden
          className="absolute inset-0 bg-cover bg-center opacity-35 transition-opacity group-hover:opacity-55"
          style={{ backgroundImage: `url("${option.imageSrc}")` }}
        />
      ) : (
        <span aria-hidden className="absolute inset-0 bg-muted/40" />
      )}
      {/* Explicit scrim: art luminance varies wildly, so the label cannot rely
          on the image staying dark enough behind it. */}
      <span
        aria-hidden
        className="absolute inset-0 bg-gradient-to-t from-background via-background/85 to-background/30"
      />
    </>
  );
}

/** One catalogue tile: art, group badge, name, and its selection position. */
function CatalogueTile({
  option,
  selectionIndex,
  disabled,
  onToggle
}: Readonly<{
  option: CatalogueItem;
  /** Position in the persisted order, or -1 when unselected. */
  selectionIndex: number;
  disabled: boolean;
  onToggle: () => void;
}>) {
  const selected = selectionIndex >= 0;
  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={option.name}
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        "group relative flex h-20 flex-col justify-between overflow-hidden rounded-lg border p-2 text-left transition-colors",
        selected
          ? "border-primary bg-primary/10 ring-2 ring-primary/40"
          : "border-border bg-card hover:border-primary/50",
        disabled && "cursor-not-allowed"
      )}
    >
      <ItemArt option={option} />
      {/* `span`, not `<Badge>`: this sits inside a `<button>`, which may only
          contain phrasing content, and `Badge` renders a `div`. */}
      <span className="relative z-10 flex items-start justify-between gap-1">
        {option.group ? (
          <span className={cn(badgeVariants({ variant: "outline" }), "bg-background/85")}>
            {option.group}
          </span>
        ) : (
          <span />
        )}
        {selected ? (
          <span
            aria-hidden
            className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold tabular-nums text-primary-foreground shadow-xs"
          >
            {selectionIndex + 1}
          </span>
        ) : null}
      </span>
      <span className="relative z-10 truncate text-xs font-semibold text-foreground">
        {option.name}
      </span>
    </button>
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

/** Selected items in stored order, each with the control that removes it. */
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
        return (
          <li key={itemId}>
            <span className="flex items-center gap-1.5 rounded-md border border-border bg-card py-1 pe-1 ps-1.5 text-xs">
              {item?.imageSrc ? (
                <Image
                  src={item.imageSrc}
                  alt=""
                  width={16}
                  height={16}
                  className="size-4 shrink-0 rounded-sm object-cover outline outline-black/10 dark:outline-white/10"
                />
              ) : (
                <span aria-hidden className="size-4 shrink-0 rounded-sm bg-muted" />
              )}
              <span className="text-muted-foreground tabular-nums">{index + 1}</span>
              <span className="max-w-40 truncate font-medium">{name}</span>
              {disabled ? null : (
                <button
                  type="button"
                  aria-label={t("poolRemove", { item: name })}
                  onClick={() => onRemove(itemId)}
                  className="relative flex size-5 items-center justify-center rounded text-muted-foreground transition-colors after:absolute after:-inset-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                >
                  <X aria-hidden className="size-3.5" />
                </button>
              )}
            </span>
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
      <Popover open={filter.open} onOpenChange={filter.onOpenChange}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            role="combobox"
            aria-expanded={filter.open}
            aria-label={props.triggerLabel}
            disabled={disabled}
            className="w-56 justify-between gap-2 font-normal"
          >
            <span className="truncate">
              <span className="text-muted-foreground">{props.triggerPrefix} </span>
              {selected ? selected.name : t("slotReserveNone")}
            </span>
            <ChevronsUpDown aria-hidden className="size-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-72 p-0">
          <Command shouldFilter={false}>
            <GroupFilterRow
              groups={filter.groups}
              total={options.length}
              value={filter.groupFilter}
              onChange={filter.setGroupFilter}
            />
            <CommandInput
              value={filter.query}
              onValueChange={filter.setQuery}
              placeholder={searchPlaceholder}
            />
            <CommandList>
              <CommandEmpty>{t("catalogueEmpty")}</CommandEmpty>
              <CommandGroup>
                <CommandItem value={t("slotReserveNone")} onSelect={() => choose(null)}>
                  <span>{t("slotReserveNone")}</span>
                  <Check
                    aria-hidden
                    className={cn(
                      "ms-auto size-4",
                      props.value == null ? "opacity-100" : "opacity-0"
                    )}
                  />
                </CommandItem>
                {filter.visibleOptions.map((option) => (
                  <CommandItem
                    key={option.id}
                    value={option.name}
                    onSelect={() => choose(option.id)}
                  >
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
                    {option.group ? (
                      <span className="truncate text-xs text-muted-foreground">{option.group}</span>
                    ) : null}
                    <Check
                      aria-hidden
                      className={cn(
                        "ms-auto size-4 shrink-0",
                        props.value === option.id ? "opacity-100" : "opacity-0"
                      )}
                    />
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
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
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          className="h-8 gap-1.5 border-dashed"
        >
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
            total={options.length}
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
              className="h-8 text-base sm:text-xs"
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
                  selectionIndex={selectionOrder.get(option.id) ?? -1}
                  disabled={disabled}
                  onToggle={() => onToggle(option.id)}
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
