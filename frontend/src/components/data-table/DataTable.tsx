"use client";

// Sticky-column and row-tint rules, moved out of globals.css and next to their
// only consumer.
import "./data-table.css";

import React, { useEffect, useId, useRef, useState } from "react";
import type { Row } from "@tanstack/react-table";

import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { InfiniteScrollFooter } from "@/components/ui/infinite-scroll";
import { useIsMobile, usePathname } from "@/components/data-table/host";
import {
  ADMIN_ACTION_COLUMN_ID,
  columnDefId,
  readColumnMeta
} from "@/components/data-table/columns";
import type { DataTableProps } from "@/components/data-table/types";
import { useColumnVisibility } from "@/components/data-table/useColumnVisibility";
import { isInteractiveRowTarget, useRowSelectionGestures } from "@/components/data-table/useRowSelectionGestures";
import { AdminTableSearchContext } from "@/components/data-table/HighlightMatch";
import { downloadCsv } from "@/components/data-table/csv";
import type { ColumnDndModule } from "@/components/data-table/ColumnDnd";
import { buildColumnLayout } from "@/components/data-table/column-layout";
import { createBodyRenderer } from "@/components/data-table/body-rows";
import { AdminTableHeader } from "@/components/data-table/AdminTableHeader";
import { AdminTableToolbar, type PickerColumn } from "@/components/data-table/AdminTableToolbar";
import { AdminTablePagination } from "@/components/data-table/AdminTablePagination";
import { AdminTableEmptyState } from "@/components/data-table/AdminTableEmptyState";
import { AdminTableMobileList } from "@/components/data-table/AdminTableMobileList";
import { useAdminTableState } from "@/components/data-table/useAdminTableState";
import { useAdminTableData } from "@/components/data-table/useAdminTableData";
import { useAdminTable } from "@/components/data-table/useAdminTable";
import { useTablePreferences } from "@/components/data-table/useTablePreferences";
import { useTableScrollBox } from "@/components/data-table/useTableScrollBox";
import { useVirtualBody } from "@/components/data-table/useVirtualBody";

const DEFAULT_PAGE_SIZE_OPTIONS = [10, 15, 25, 50, 100];

/**
 * The admin list table: toolbar, sticky header, virtualised body, footer.
 *
 * This file is the orchestrator — state, the table instance and the body's
 * rows. Everything with a seam of its own lives next to it: the URL state
 * (`useAdminTableState`), the two data modes (`useAdminTableData`), column
 * geometry (`column-layout`), the cells (`head-cell`, `body-cells`) and the
 * chrome (`AdminTableToolbar`, `AdminTablePagination`, `AdminTableMobileList`).
 */
export function DataTable<TData>({
  queryKey,
  queryFn,
  rows,
  isLoading = false,
  columns,
  searchPlaceholder,
  emptyMessage = "No records to show yet.",
  onRowClick,
  onRowDoubleClick,
  actions,
  initialPageSize = 15,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  filterKey,
  initialSort,
  filters: controlledFilters,
  onFiltersChange,
  getRowId,
  enableRowSelection,
  bulkActions,
  renderExpanded,
  groupRows,
  columnsStorageKey,
  paging = "pages",
  rowUnit = "rows",
  cellAlign = "middle",
  toolbar,
  inspectorId,
  renderMobileCard,
}: Readonly<DataTableProps<TData>>) {
  const isClientMode = rows !== undefined;
  // Server mode has no accumulating query to grow, so it always paginates.
  const isInfinite = isClientMode && paging === "infinite";
  // Every row at once: the caller already holds the whole pool and wants no
  // batching UI over it.
  const showAll = isClientMode && paging === "all";
  const pathname = usePathname();
  const isMobile = useIsMobile();
  const searchInputId = useId();
  const rowHintId = useId();

  const {
    searchValue,
    setSearchValue,
    debouncedSearchValue,
    currentPage,
    setCurrentPage,
    pageSize,
    setPageSize,
    sorting,
    setSorting,
    sortField,
    sortDir,
    filters,
    setFilters,
    serializedFilters
  } = useAdminTableState({
    columns,
    pathname,
    initialPageSize,
    initialSort,
    filterKey,
    filters: controlledFilters,
    onFiltersChange
  });

  // Per-user preferences are per screen, falling back to the route when the
  // screen gave no key.
  // ponytail: two tables on one route without `columnsStorageKey` share prefs.
  const prefsKey = columnsStorageKey ?? `admin-table:${pathname}`;
  const { density, setDensity, columnSizing, setColumnSizing, columnOrder, setColumnOrder } =
    useTablePreferences(prefsKey, columns);
  const { scrollElement, tableRef, cardRef } = useTableScrollBox();

  const { data, clientRows, isRefreshing } = useAdminTableData({
    queryKey,
    queryFn,
    rows,
    columns,
    isClientMode,
    isLoading,
    page: currentPage,
    search: debouncedSearchValue,
    pageSize,
    sortField,
    sortDir,
    filters
  });

  const pickerColumns = columns
    .map((column) => {
      const meta = readColumnMeta<TData>(column.meta);
      return {
        id: columnDefId(column),
        label: column.header as React.ReactNode,
        category: meta.category,
        defaultVisible: !meta.defaultHidden,
        mandatory: meta.mandatory === true
      };
    })
    .filter((column): column is PickerColumn =>
      Boolean(column.id) && column.category !== undefined,
    );
  const { visibility, toggleColumn, setVisibility, resetToDefaults } = useColumnVisibility(
    columnsStorageKey ?? null,
    pickerColumns,
  );

  const { table, rowSelection, setRowSelection } = useAdminTable({
    columns,
    data: isClientMode ? clientRows : (data.results ?? []),
    getRowId,
    enableRowSelection,
    renderExpanded,
    isClientMode,
    showAll,
    isInfinite,
    rowCount: data.total ?? 0,
    page: currentPage,
    pageSize,
    setCurrentPage,
    setPageSize,
    filters,
    sorting,
    setSorting,
    columnSizing,
    setColumnSizing,
    columnOrder,
    visibility
  });

  const clientFilteredCount = isClientMode ? table.getFilteredRowModel().rows.length : 0;
  const safeTotal = isClientMode
    ? clientFilteredCount
    : Number.isFinite(data.total)
      ? data.total
      : 0;
  const responsePageSize = !isClientMode && Number.isFinite(data.per_page) ? data.per_page : undefined;
  const effectivePageSize = responsePageSize && responsePageSize > 0 ? responsePageSize : pageSize;
  const availablePageSizeOptions = Array.from(new Set([...pageSizeOptions, effectivePageSize])).sort((a, b) => a - b);
  const totalPageCount = Math.max(1, Math.ceil(safeTotal / effectivePageSize));
  const rangeStart = safeTotal > 0 ? (currentPage - 1) * effectivePageSize + 1 : 0;
  const rangeEnd = safeTotal > 0 ? Math.min(currentPage * effectivePageSize, safeTotal) : 0;
  const pageRows = table.getRowModel().rows;
  // Server mode only holds the current page, so a row selected two pages back
  // would vanish from `bulkActions` while its checkbox state lived on. Remember
  // every selected row's data as it passes through; forget it when deselected.
  const selectedDataRef = useRef(new Map<string, TData>());
  for (const row of pageRows) if (row.getIsSelected()) selectedDataRef.current.set(row.id, row.original);
  for (const id of selectedDataRef.current.keys()) if (!rowSelection[id]) selectedDataRef.current.delete(id);
  const selectedData = [...selectedDataRef.current.values()];
  const selectedOnPage = pageRows.filter((row) => row.getIsSelected()).length;
  const gestures = useRowSelectionGestures(table, Boolean(enableRowSelection));
  const selectableRows = enableRowSelection ? pageRows.filter((row) => row.getCanSelect()) : [];

  useEffect(() => {
    if (currentPage > totalPageCount) {
      setCurrentPage(totalPageCount);
    }
  }, [currentPage, totalPageCount]);

  const rowClickTimeoutRef = useRef<number | null>(null);
  useEffect(() => {
    return () => {
      if (rowClickTimeoutRef.current !== null) window.clearTimeout(rowClickTimeoutRef.current);
    };
  }, []);

  const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
  /** Text of the cell under the last right-click, offered as "Copy" in the row menu. */
  const [contextCell, setContextCell] = useState("");

  const hasRowAction = Boolean(onRowClick || onRowDoubleClick);
  const hasLeadingColumn = Boolean(enableRowSelection || renderExpanded);
  const layout = buildColumnLayout({ table, columns, columnSizing, hasLeadingColumn, density });
  const { visibleColumns, bodyColumnCount } = layout;

  const { rowGroups, bodyItems, virtualize, virtualizer, virtualItems, padTop, padBottom, firstRowId } =
    useVirtualBody({
      pageRows,
      groupRows,
      hasExpandedDetail: Boolean(renderExpanded),
      isMobile,
      density,
      scrollElement
    });
  // Roving tabindex: one row is in the Tab order, arrows move between the rest.
  const tabbableRowId = focusedRowId !== null && table.getRowModel().rowsById[focusedRowId] ? focusedRowId : firstRowId;

  const handleRowClick = (event: React.MouseEvent<HTMLTableRowElement>, row: Row<TData>) => {
    // A sweep, Ctrl+click or Shift+click ends in a click too; that one selected, it does not open.
    if (gestures.consumeClick()) return;
    if (!onRowClick) return;
    if (isInteractiveRowTarget(event.target as HTMLElement)) return;

    if (onRowDoubleClick) {
      if (rowClickTimeoutRef.current !== null) window.clearTimeout(rowClickTimeoutRef.current);
      rowClickTimeoutRef.current = window.setTimeout(() => { onRowClick(row); rowClickTimeoutRef.current = null; }, 200);
      return;
    }
    onRowClick(row);
  };

  const handleRowDoubleClick = (event: React.MouseEvent<HTMLTableRowElement>, row: Row<TData>) => {
    if (!onRowDoubleClick) return;
    if (isInteractiveRowTarget(event.target as HTMLElement)) return;
    if (rowClickTimeoutRef.current !== null) { window.clearTimeout(rowClickTimeoutRef.current); rowClickTimeoutRef.current = null; }
    onRowDoubleClick(row);
  };

  /** Arrow/Space/Escape/Ctrl+A go to the selection gestures; Enter (and Space without selection) opens the row. */
  const handleBodyKeyDown = (event: React.KeyboardEvent<HTMLTableSectionElement>) => {
    if (gestures.bodyKeyDown(event)) return;
    if (!onRowClick) return;
    const target = event.target as HTMLElement;
    if (target.dataset.rowId === undefined) return;
    const row = table.getRowModel().rowsById[target.dataset.rowId];
    if (row && (event.key === "Enter" || (event.key === " " && !enableRowSelection))) {
      event.preventDefault();
      onRowClick(row);
    }
  };

  // Column drag-to-reorder. Only the header row is sortable; the actions
  // column keeps its place at the right edge. `@dnd-kit` is fetched when a
  // pointer first reaches the table (see `armColumnDnd`), not shipped with it,
  // so a list page that is only read never downloads it.
  const [columnDnd, setColumnDnd] = useState<ColumnDndModule | null>(null);
  const columnDndRequestedRef = useRef(false);
  const armColumnDnd = () => {
    if (columnDndRequestedRef.current) return;
    columnDndRequestedRef.current = true;
    void import("@/components/data-table/ColumnDnd").then(setColumnDnd);
  };
  // dnd-kit's `arrayMove`: drop the dragged id, reinsert it at the index the
  // drop target holds in the order it was dragged from.
  const handleColumnReorder = (activeId: string, overId: string) => {
    const next = columnOrder.filter((id) => id !== activeId);
    next.splice(columnOrder.indexOf(overId), 0, activeId);
    setColumnOrder(next);
  };

  /** Selected rows when there are any, else the whole current view (every filtered row in client mode). */
  const exportCsv = () => {
    const exportColumns = visibleColumns.filter((column) => column.id !== ADMIN_ACTION_COLUMN_ID);
    const source = isClientMode ? table.getFilteredRowModel().rows : pageRows;
    const exportRows = selectedData.length > 0 ? source.filter((row) => row.getIsSelected()) : source;
    downloadCsv(pathname.split("/").filter(Boolean).pop() ?? "export", [
      exportColumns.map((column) => (typeof column.columnDef.header === "string" ? column.columnDef.header : column.id)),
      ...exportRows.map((row) => exportColumns.map((column) => row.getValue(column.id)))
    ]);
  };

  // Right-click / long-press menu mirrors the kebab column, when a screen has one.
  const rowActions = columns.map((column) => readColumnMeta<TData>(column.meta).rowActions).find(Boolean);
  // Only cells left on TanStack's default renderer get search highlighting;
  // custom cells opt in through `useAdminTableSearch`.
  const customCellIds = new Set(columns.filter((column) => column.cell !== undefined).map(columnDefId));
  const cellPadding = density === "compact" ? "py-1" : "py-2.5";
  const renderItem = createBodyRenderer<TData>({
    layout,
    cell: { layout, cellPadding, cellAlign, hasLeadingColumn, customCellIds, search: debouncedSearchValue },
    leading: hasLeadingColumn
      ? {
          layout,
          cellPadding,
          cellAlign,
          enableRowSelection: Boolean(enableRowSelection),
          hasExpandedDetail: Boolean(renderExpanded),
          gestures
        }
      : undefined,
    virtualizer,
    gestures,
    inspectorId,
    tabbableRowId,
    onRowFocus: setFocusedRowId,
    hasRowAction,
    onRowClick: handleRowClick,
    onRowDoubleClick: handleRowDoubleClick,
    contextCell,
    onContextCellChange: setContextCell,
    rowActions,
    rowHintId,
    renderExpanded
  });

  /**
   * The built-in search box stays unless a `toolbar` was handed in without a
   * `searchPlaceholder` — that is the screen saying "my filter bar owns the
   * search". Passing both keeps the table's own box, for a toolbar that is
   * only chips.
   */
  const showSearch = searchPlaceholder !== undefined || toolbar === undefined;
  const searchLabel = searchPlaceholder ?? "Search…";

  const emptyState = (
    <AdminTableEmptyState
      message={emptyMessage}
      hasSearch={Boolean(searchValue)}
      hasFilters={Boolean(serializedFilters)}
      onClear={() => { setSearchValue(""); setFilters({}); }}
    />
  );

  const offPageSelected = selectedData.length - selectedOnPage;

  return (
    <AdminTableSearchContext.Provider value={debouncedSearchValue}>
    <div ref={cardRef} className="rounded-xl border border-border/50 bg-card/50 overflow-hidden">
      <AdminTableToolbar
        showSearch={showSearch}
        searchInputId={searchInputId}
        searchLabel={searchLabel}
        searchValue={searchValue}
        onSearchChange={setSearchValue}
        toolbar={toolbar}
        isRefreshing={isRefreshing}
        bulkActions={bulkActions && selectedData.length > 0 ? bulkActions(selectedData, () => setRowSelection({})) : null}
        offPageSelected={offPageSelected}
        selectedCount={selectedData.length}
        onExportCsv={exportCsv}
        canExport={pageRows.length > 0}
        density={density}
        onToggleDensity={() => setDensity(density === "compact" ? "comfortable" : "compact")}
        prefsKey={prefsKey}
        visibility={visibility}
        onVisibilityChange={setVisibility}
        pickerColumns={columnsStorageKey ? pickerColumns : undefined}
        onToggleColumn={toggleColumn}
        onResetColumns={resetToDefaults}
        actions={actions}
      />

      {/* ── TABLE ───────────────────────────────────────── */}
      <div>
        <p id={rowHintId} className="sr-only">
          Use the Up and Down arrows to move between rows
          {enableRowSelection ? ", Space to select, Shift with an arrow to extend the selection" : ""}
          {onRowClick ? ", Enter to open the focused row" : ""}.
        </p>
        {isMobile ? (
          pageRows.length > 0 ? (
            <AdminTableMobileList
              rows={rowGroups.flatMap((group) => group.rows)}
              visibleColumns={visibleColumns}
              renderMobileCard={renderMobileCard}
              inspectorId={inspectorId}
              onRowClick={onRowClick}
            />
          ) : (
            <div className="py-8 text-center">{emptyState}</div>
          )
        ) : (
        // The table scrolls in its own box so the header can stick and the
        // body can be virtualised; the box's height is measured to fill the
        // viewport (see `useTableScrollBox`).
        <Table
          ref={tableRef}
          className="min-w-full border-separate border-spacing-0"
          // A pointer reaching the table is the warning a column drag gives:
          // the reorder chunk is fetched then, usually before the header is hit.
          onPointerEnter={armColumnDnd}
        >
          <AdminTableHeader
            table={table}
            layout={layout}
            density={density}
            sorting={sorting}
            isClientMode={isClientMode}
            hasLeadingColumn={hasLeadingColumn}
            enableRowSelection={Boolean(enableRowSelection)}
            selectableRows={selectableRows}
            columnDnd={columnDnd}
            onReorder={handleColumnReorder}
            onArmDnd={armColumnDnd}
          />
          <TableBody onKeyDown={handleBodyKeyDown}>
            {bodyItems.length === 0 ? (
              <TableRow>
                <TableCell colSpan={bodyColumnCount} className="py-8 text-center">
                  {emptyState}
                </TableCell>
              </TableRow>
            ) : virtualize ? (
              <>
                {padTop > 0 ? <tr aria-hidden style={{ height: padTop }} /> : null}
                {virtualItems.map((virtual) => renderItem(bodyItems[virtual.index], virtual))}
                {padBottom > 0 ? <tr aria-hidden style={{ height: padBottom }} /> : null}
              </>
            ) : (
              bodyItems.map((item) => renderItem(item))
            )}
            {safeTotal > 0 && isInfinite ? (
              // Inside the scroll box, where the sentinel is only in view once
              // the user has actually reached the bottom of the loaded rows.
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={bodyColumnCount} className="border-t border-border/40 px-4 py-3">
                  <InfiniteScrollFooter
                    root={scrollElement}
                    loaded={pageRows.length}
                    total={safeTotal}
                    unit={rowUnit}
                    hasNextPage={pageRows.length < safeTotal}
                    // Client mode already holds every row, so a batch appears in
                    // the same commit — there is no in-flight page to report.
                    isFetchingNextPage={false}
                    fetchNextPage={() => setCurrentPage(currentPage + 1)}
                  />
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
        )}
      </div>

      {safeTotal > 0 && !isInfinite && !showAll && (
        <AdminTablePagination
          total={safeTotal}
          rangeStart={rangeStart}
          rangeEnd={rangeEnd}
          currentPage={currentPage}
          totalPageCount={totalPageCount}
          onPageChange={setCurrentPage}
          pageSize={effectivePageSize}
          pageSizeOptions={availablePageSizeOptions}
          onPageSizeChange={(next) => { setCurrentPage(1); setPageSize(next); }}
        />
      )}
    </div>
    </AdminTableSearchContext.Provider>
  );
}
