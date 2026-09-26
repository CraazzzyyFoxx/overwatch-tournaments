"use client";

import React from "react";
import { Download, Rows3, Rows4, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { CategorizedColumnPicker } from "@/components/ui/categorized-column-picker";
import type { AdminColumnCategory } from "@/components/data-table/columns";
import { AdminSavedViews } from "@/components/data-table/SavedViews";
import type { AdminTableDensity } from "@/components/data-table/useTablePreferences";

const COLUMN_CATEGORY_LABELS: Record<AdminColumnCategory, string> = {
  core: "Core",
  meta: "Meta",
  admin: "Admin"
};

/** One offerable column, as the picker and the visibility store see it. */
export interface PickerColumn {
  id: string;
  label: React.ReactNode;
  category: AdminColumnCategory;
  defaultVisible: boolean;
  mandatory: boolean;
}

export interface AdminTableToolbarProps {
  showSearch: boolean;
  searchInputId: string;
  searchLabel: string;
  searchValue: string;
  onSearchChange: (value: string) => void;
  /** The screen's own filter bar, between the search box and the table's controls. */
  toolbar?: React.ReactNode;
  isRefreshing: boolean;
  /** Already resolved against the current selection by the table. */
  bulkActions?: React.ReactNode;
  /** Selected rows that are not on the current page, which bulk actions still include. */
  offPageSelected: number;
  selectedCount: number;
  onExportCsv: () => void;
  canExport: boolean;
  density: AdminTableDensity;
  onToggleDensity: () => void;
  prefsKey: string;
  visibility: Record<string, boolean>;
  onVisibilityChange: (next: Record<string, boolean>) => void;
  /** Absent when the screen gave no `columnsStorageKey`: no picker then. */
  pickerColumns?: PickerColumn[];
  onToggleColumn: (id: string) => void;
  onResetColumns: () => void;
  actions?: React.ReactNode;
}

/**
 * One row above the table: search, the screen's filter bar (chips wrap inside
 * it), then the table's own controls. Two stacked rows cost a full band of
 * chrome for a chip row that is empty most of the time.
 */
export function AdminTableToolbar({
  showSearch,
  searchInputId,
  searchLabel,
  searchValue,
  onSearchChange,
  toolbar,
  isRefreshing,
  bulkActions,
  offPageSelected,
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
  actions
}: Readonly<AdminTableToolbarProps>) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-border/40 px-4 py-2.5">
      {showSearch ? (
        <div className="relative w-64 shrink-0">
          <Label htmlFor={searchInputId} className="sr-only">{searchLabel}</Label>
          <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            id={searchInputId}
            autoComplete="off"
            className="h-8 border-border bg-muted/30 pl-9 text-sm placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-ring focus-visible:border-ring"
            name="admin-table-search"
            placeholder={searchLabel}
            value={searchValue}
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </div>
      ) : null}

      {toolbar ? <div className="min-w-0 flex-1">{toolbar}</div> : null}

      {isRefreshing ? (
        <output className="flex shrink-0 items-center text-muted-foreground">
          <Spinner className="size-3" />
          <span className="sr-only">Refreshing results…</span>
        </output>
      ) : null}

      <div className="ml-auto flex shrink-0 items-center gap-2">
        {bulkActions}
        {offPageSelected > 0 ? (
          <span className="text-xs tabular-nums text-muted-foreground" title="Selected rows not on this page are included in bulk actions">
            {offPageSelected} on other pages
          </span>
        ) : null}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8"
          onClick={onExportCsv}
          disabled={!canExport}
          title={selectedCount > 0 ? `Export ${selectedCount} selected rows as CSV` : "Export the current view as CSV"}
        >
          <Download aria-hidden className="size-3.5" />
          CSV
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 w-8 px-0"
          aria-pressed={density === "compact"}
          aria-label={density === "compact" ? "Comfortable rows" : "Compact rows"}
          title={density === "compact" ? "Comfortable rows" : "Compact rows"}
          onClick={onToggleDensity}
        >
          {density === "compact" ? <Rows3 aria-hidden className="size-3.5" /> : <Rows4 aria-hidden className="size-3.5" />}
        </Button>
        <AdminSavedViews
          storageKey={prefsKey}
          extra={{ get: () => visibility, apply: (next) => onVisibilityChange(next as Record<string, boolean>) }}
        />
        {pickerColumns ? (
          <CategorizedColumnPicker<AdminColumnCategory, PickerColumn>
            columns={pickerColumns}
            categories={["core", "meta", "admin"]}
            categoryLabel={(category) => COLUMN_CATEGORY_LABELS[category]}
            visibility={visibility}
            onToggle={onToggleColumn}
            onReset={onResetColumns}
            triggerLabel="Columns"
            resetLabel="Reset to defaults"
            isMandatory={(id) => pickerColumns.some((column) => column.id === id && column.mandatory)}
          />
        ) : null}
        {actions}
      </div>
    </div>
  );
}
