"use client";

import React, { useCallback, useId, useState, useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Bookmark,
  ChevronLeft,
  ChevronRight,
  Download,
  Layers,
  Settings2,
  SlidersHorizontal
} from "lucide-react";
import type { ColumnSort } from "@tanstack/react-table";

import { Link, cn } from "@/components/data-table/host";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { SearchField } from "@/components/ui/search-field";
import { Spinner } from "@/components/ui/spinner";
import type { AdminColumnCategory } from "@/components/data-table/columns";
import { useSavedViews } from "@/components/data-table/SavedViews";
import { TableToolbarContext } from "@/components/data-table/toolbar-context";
import type { DataTableGroupBy, TableCommand } from "@/components/data-table/types";
import type { AdminTableDensity } from "@/components/data-table/useTablePreferences";

/** One offerable column, as the picker and the visibility store see it. */
export interface PickerColumn {
  id: string;
  label: React.ReactNode;
  category: AdminColumnCategory;
  defaultVisible: boolean;
  mandatory: boolean;
}

/** Sorting from the View menu, for cards: they have no header to click. */
export interface AdminTableSort {
  columns: { id: string; label: React.ReactNode }[];
  /** Cards sort by one column at a time. */
  value?: ColumnSort;
  onChange: (next: ColumnSort) => void;
}

/** The table's own controls over how its rows are shown: everything behind the "View" menu. */
export interface AdminTableViewProps {
  selectedCount: number;
  onExportCsv: () => void;
  canExport: boolean;
  /** Absent where the rows are cards, which have no density. */
  density?: AdminTableDensity;
  onToggleDensity: () => void;
  prefsKey: string;
  visibility: Record<string, boolean>;
  onVisibilityChange: (next: Record<string, boolean>) => void;
  /** Absent when the screen gave no `columnsStorageKey`, or its own cards replace the columns. */
  pickerColumns?: PickerColumn[];
  onToggleColumn: (id: string) => void;
  onResetColumns: () => void;
  groupBy?: DataTableGroupBy;
  sort?: AdminTableSort;
}

export interface AdminTableToolbarProps {
  ref?: React.Ref<HTMLDivElement>;
  /** From `useNarrowToolbar`: the toolbar's own width, not the window's. */
  narrow: boolean;
  showSearch: boolean;
  searchInputId: string;
  searchLabel: string;
  searchValue: string;
  onSearchChange: (value: string) => void;
  /** The screen's `FilterBar`. */
  filters?: React.ReactNode;
  isRefreshing: boolean;
  /** The visible ones: `hidden` is already dropped. */
  commands: TableCommand[];
  view: AdminTableViewProps;
}

const CATEGORIES: readonly AdminColumnCategory[] = ["core", "meta", "admin"];

/**
 * Below this width the toolbar folds. It is the toolbar's own width, so a
 * table squeezed beside an open Inspector folds on a wide screen too; a
 * phone is always under it.
 */
const NARROW_TOOLBAR_PX = 640;

/**
 * Whether the toolbar the returned ref lands on is narrow, read through an
 * external-store subscription so a resize re-renders before the frame paints.
 * Zero width — not laid out yet, a hidden tab, a test DOM — keeps the wide row.
 */
export function useNarrowToolbar(): [(node: HTMLDivElement | null) => void, boolean] {
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (!node || typeof ResizeObserver === "undefined") return () => {};
      const observer = new ResizeObserver(onChange);
      observer.observe(node);
      return () => observer.disconnect();
    },
    [node]
  );
  const narrow = useSyncExternalStore(
    subscribe,
    () => {
      const width = node?.getBoundingClientRect().width ?? 0;
      return width > 0 && width < NARROW_TOOLBAR_PX;
    },
    () => false
  );

  return [setNode, narrow];
}

/**
 * One row above the table in three zones, each with one meaning: what
 * narrows the list (the search, the screen's `FilterBar`), how it is shown
 * (the "View" menu), and what the screen does with it (`commands`, the one
 * primary last).
 *
 * Narrow, it stays one row: the search, the filter picker as an icon, the
 * "View" menu — which then opens with the secondary commands — and the
 * primary as its icon. Active filter chips and a disabled primary's reason
 * drop to a row of their own, only while there are any.
 */
export function AdminTableToolbar({
  ref,
  narrow,
  showSearch,
  searchInputId,
  searchLabel,
  searchValue,
  onSearchChange,
  filters,
  isRefreshing,
  commands,
  view
}: Readonly<AdminTableToolbarProps>) {
  const t = useTranslations("kitTable.dataTableExtra");
  const primary = commands.find((command) => command.primary);
  const secondary = commands.filter((command) => command !== primary);

  return (
    <TableToolbarContext.Provider value={narrow}>
      <div
        ref={ref}
        className={cn(
          "flex flex-wrap items-center border-b border-border/40 px-4 py-2.5",
          narrow ? "gap-2" : "gap-3"
        )}
      >
        {showSearch ? (
          <SearchField
            id={searchInputId}
            containerClassName={narrow ? "min-w-40 flex-1" : "w-64 shrink-0"}
            autoComplete="off"
            name="admin-table-search"
            label={searchLabel}
            placeholder={searchLabel}
            value={searchValue}
            onValueChange={onSearchChange}
          />
        ) : null}

        {/* Narrow, the filter bar's pieces are this row's own items: its picker beside the search, its chips below.
            Wide, it is sized by its chips (`grow`, not `flex-1`): when they and the commands do not fit one line,
            the commands wrap under them instead of the chips folding into a column. */}
        {filters ? <div className={narrow ? "contents" : "min-w-0 grow"}>{filters}</div> : null}

        {isRefreshing ? (
          <output className="flex shrink-0 items-center text-muted-foreground">
            <Spinner className="size-3" />
            <span className="sr-only">{t("refreshing")}</span>
          </output>
        ) : null}

        {narrow ? (
          <>
            <ViewMenu {...view} narrow commands={secondary} />
            {primary ? <CommandButton command={primary} narrow /> : null}
          </>
        ) : (
          <div className="ml-auto flex max-w-full flex-wrap items-center justify-end gap-2">
            <ViewMenu {...view} narrow={false} commands={[]} />
            {secondary.map((command) => (
              <CommandButton key={command.id} command={command} narrow={false} />
            ))}
            {primary ? <CommandButton command={primary} narrow={false} /> : null}
          </div>
        )}
      </div>
    </TableToolbarContext.Provider>
  );
}

/** Spinner while in flight, else the command's icon. */
function CommandGlyph({ command }: Readonly<{ command: TableCommand }>) {
  const Icon = command.icon;
  if (command.pending) return <Spinner />;
  return Icon ? <Icon aria-hidden /> : null;
}

/**
 * A command as a button. Narrow, the primary shrinks to its icon (a command
 * without one keeps its label) and its reason takes the toolbar's last row.
 */
function CommandButton({ command, narrow }: Readonly<{ command: TableCommand; narrow: boolean }>) {
  const reasonId = useId();
  const iconOnly = narrow && command.icon !== undefined;
  const disabled = command.disabled === true || command.disabledReason !== undefined;
  const props = {
    variant: command.primary ? ("default" as const) : ("outline" as const),
    size: "sm" as const,
    className: iconOnly ? "w-8 px-0" : undefined,
    "aria-label": iconOnly ? command.label : undefined,
    title: iconOnly ? command.label : undefined,
    "aria-describedby": command.disabledReason ? reasonId : undefined
  };
  const content = (
    <>
      <CommandGlyph command={command} />
      {iconOnly ? null : command.label}
    </>
  );
  const reason = command.disabledReason ? (
    <span id={reasonId} className={cn("text-caption text-muted-foreground", narrow && "order-last basis-full")}>
      {command.disabledReason}
    </span>
  ) : null;

  return (
    <>
      {narrow ? null : reason}
      {command.href !== undefined && !disabled ? (
        <Button asChild {...props}>
          <Link href={command.href}>{content}</Link>
        </Button>
      ) : (
        <Button type="button" {...props} disabled={disabled} onClick={command.onSelect}>
          {content}
        </Button>
      )}
      {narrow ? reason : null}
    </>
  );
}

/** A secondary command folded into the narrow "View" menu; a reason reads under its label. */
function CommandMenuItem({ command }: Readonly<{ command: TableCommand }>) {
  const disabled = command.disabled === true || command.disabledReason !== undefined;
  const content = (
    <>
      <CommandGlyph command={command} />
      {command.disabledReason ? (
        <span className="flex min-w-0 flex-col">
          {command.label}
          <span className="text-caption text-muted-foreground">{command.disabledReason}</span>
        </span>
      ) : (
        command.label
      )}
    </>
  );

  return command.href !== undefined && !disabled ? (
    <DropdownMenuItem asChild>
      <Link href={command.href}>{content}</Link>
    </DropdownMenuItem>
  ) : (
    <DropdownMenuItem disabled={disabled} onSelect={command.onSelect}>
      {content}
    </DropdownMenuItem>
  );
}

type ViewLevel = "root" | "sort" | "group" | "views" | "columns";

/**
 * How the rows are shown, in one menu on every width: CSV, density, then
 * grouping, saved views and columns as a second level that replaces the
 * items — a side submenu has no room beside a menu on a phone and runs off
 * the screen edge. Narrow, the secondary commands lead it.
 */
function ViewMenu({
  narrow,
  commands,
  selectedCount,
  onExportCsv,
  canExport,
  density,
  onToggleDensity,
  prefsKey,
  visibility,
  onVisibilityChange,
  pickerColumns,
  onToggleColumn,
  onResetColumns,
  groupBy,
  sort
}: Readonly<AdminTableViewProps & { narrow: boolean; commands: TableCommand[] }>) {
  const t = useTranslations("kitTable.dataTableExtra");
  const actionsT = useTranslations("kit.actions");
  const savedViews = useSavedViews(prefsKey, {
    get: () => visibility,
    apply: (next) => onVisibilityChange(next as Record<string, boolean>)
  });
  const [level, setLevel] = useState<ViewLevel>("root");

  /** `preventDefault` keeps the menu open while it switches level. */
  const enter = (next: ViewLevel) => (event: Event) => {
    event.preventDefault();
    if (next === "views") savedViews.reload();
    setLevel(next);
  };
  const levelTitle =
    level === "sort" ? t("sort") : level === "group" ? groupBy?.label : level === "views" ? t("views") : t("columns");
  const sortLabel = sort?.columns.find((column) => column.id === sort.value?.id)?.label;

  return (
    <>
      <DropdownMenu onOpenChange={(open) => (open ? undefined : setLevel("root"))}>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className={narrow ? "ml-auto w-8 px-0" : undefined}
            aria-label={narrow ? t("view") : undefined}
            title={narrow ? t("view") : undefined}
          >
            <SlidersHorizontal aria-hidden className="size-3.5" />
            {narrow ? null : t("view")}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          {level === "root" ? (
            <>
              {commands.length > 0 ? (
                <>
                  {commands.map((command) => (
                    <CommandMenuItem key={command.id} command={command} />
                  ))}
                  <DropdownMenuSeparator />
                </>
              ) : null}
              <DropdownMenuItem disabled={!canExport} onSelect={onExportCsv}>
                <Download aria-hidden />
                {selectedCount > 0 ? t("exportSelected", { count: selectedCount }) : t("exportCurrent")}
              </DropdownMenuItem>
              {density ? (
                <DropdownMenuCheckboxItem checked={density === "compact"} onCheckedChange={onToggleDensity}>
                  {t("compactRows")}
                </DropdownMenuCheckboxItem>
              ) : null}
              {groupBy ? (
              {sort?.columns.length ? (
                <DropdownMenuItem onSelect={enter("sort")}>
                  <ArrowUpDown aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{t("sort")}</span>
                  {sortLabel ? (
                    <span className="flex min-w-0 items-center gap-1 text-caption text-muted-foreground">
                      <span className="truncate">{sortLabel}</span>
                      {sort.value?.desc ? (
                        <ArrowDown aria-label={t("sortDesc")} className="size-3 shrink-0" />
                      ) : (
                        <ArrowUp aria-label={t("sortAsc")} className="size-3 shrink-0" />
                      )}
                    </span>
                  ) : null}
                  <ChevronRight aria-hidden />
                </DropdownMenuItem>
              ) : null}
                <DropdownMenuItem onSelect={enter("group")}>
                  <Layers aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{groupBy.label}</span>
                  <span className="text-caption text-muted-foreground">
                    {groupBy.options.find((option) => option.value === groupBy.value)?.label}
                  </span>
                  <ChevronRight aria-hidden />
                </DropdownMenuItem>
              ) : null}
              <DropdownMenuItem onSelect={enter("views")}>
                <Bookmark aria-hidden />
                {t("views")}
                <ChevronRight aria-hidden className="ml-auto" />
              </DropdownMenuItem>
              {pickerColumns ? (
                <DropdownMenuItem onSelect={enter("columns")}>
                  <Settings2 aria-hidden />
                  {t("columns")}
                  <ChevronRight aria-hidden className="ml-auto" />
                </DropdownMenuItem>
              ) : null}
            </>
          ) : (
            <>
              <DropdownMenuItem aria-label={actionsT("back")} onSelect={enter("root")}>
                <ChevronLeft aria-hidden />
                {levelTitle}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              {level === "group" && groupBy ? (
              {level === "sort" && sort ? (
                <>
                  <DropdownMenuRadioGroup
                    value={sort.value?.id ?? ""}
                    onValueChange={(id) => sort.onChange({ id, desc: sort.value?.desc ?? false })}
                  >
                    {sort.columns.map((column) => (
                      <DropdownMenuRadioItem
                        key={column.id}
                        value={column.id}
                        // Stay open: the direction is picked next.
                        onSelect={(event) => event.preventDefault()}
                      >
                        {column.label}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuRadioGroup
                    value={sort.value?.desc ? "desc" : "asc"}
                    onValueChange={(dir) => sort.value && sort.onChange({ id: sort.value.id, desc: dir === "desc" })}
                  >
                    <DropdownMenuRadioItem value="asc" disabled={!sort.value} onSelect={(event) => event.preventDefault()}>
                      <ArrowUp aria-hidden className="size-3.5" />
                      {t("sortAsc")}
                    </DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value="desc" disabled={!sort.value} onSelect={(event) => event.preventDefault()}>
                      <ArrowDown aria-hidden className="size-3.5" />
                      {t("sortDesc")}
                    </DropdownMenuRadioItem>
                  </DropdownMenuRadioGroup>
                </>
              ) : null}
                <DropdownMenuRadioGroup value={groupBy.value} onValueChange={groupBy.onChange}>
                  {groupBy.options.map((option) => (
                    <DropdownMenuRadioItem key={option.value} value={option.value}>
                      {option.label}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              ) : null}
              {level === "views" ? savedViews.items : null}
              {level === "columns" && pickerColumns ? (
                <>
                  {CATEGORIES.map((category) => {
                    const columns = pickerColumns.filter((column) => column.category === category);
                    if (columns.length === 0) return null;
                    return (
                      <DropdownMenuGroup key={category}>
                        <DropdownMenuLabel>{t(category)}</DropdownMenuLabel>
                        {columns.map((column) => (
                          <DropdownMenuCheckboxItem
                            key={column.id}
                            checked={column.mandatory || visibility[column.id] !== false}
                            disabled={column.mandatory}
                            onCheckedChange={() => onToggleColumn(column.id)}
                            // Stay open: columns are toggled several at a time.
                            onSelect={(event) => event.preventDefault()}
                          >
                            {column.label}
                          </DropdownMenuCheckboxItem>
                        ))}
                      </DropdownMenuGroup>
                    );
                  })}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onSelect={(event) => {
                      event.preventDefault();
                      onResetColumns();
                    }}
                  >
                    {t("resetColumns")}
                  </DropdownMenuItem>
                </>
              ) : null}
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {savedViews.dialog}
    </>
  );
}
