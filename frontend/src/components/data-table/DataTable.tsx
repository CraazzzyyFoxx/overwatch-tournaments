"use client";

// Sticky-column and row-tint rules, moved out of globals.css and next to their
// only consumer.
import "./data-table.css";

import React, { useEffect, useEffectEvent, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import type { Row } from "@tanstack/react-table";

import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { InfiniteScrollFooter } from "@/components/ui/infinite-scroll";
import { DataPagination } from "@/components/ui/data-pagination";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useIsMobile, usePathname } from "@/components/data-table/host";
import {
  ADMIN_ACTION_COLUMN_ID,
  columnDefId,
  readColumnMeta
} from "@/components/data-table/columns";
import type { DataTableProps } from "@/components/data-table/types";
import { useColumnVisibility } from "@/components/data-table/useColumnVisibility";
import { isInteractiveRowTarget, useRowSelectionGestures } from "@/components/data-table/useRowSelectionGestures";
import { downloadCsv } from "@/components/data-table/csv";
import type { ColumnDndModule } from "@/components/data-table/ColumnDnd";
import { buildColumnLayout } from "@/components/data-table/column-layout";
import { renderBodyItem, type RowHandlers, type SharedRowProps } from "@/components/data-table/body-rows";
import { AdminRowContextMenu } from "@/components/data-table/AdminRowContextMenu";
import { AdminTableHeader } from "@/components/data-table/AdminTableHeader";
import { AdminTableToolbar, useNarrowToolbar, type PickerColumn } from "@/components/data-table/AdminTableToolbar";
import { BulkBar } from "@/components/data-table/BulkBar";
import { AdminTableEmptyState } from "@/components/data-table/AdminTableEmptyState";
import { AdminTableMobileList } from "@/components/data-table/AdminTableMobileList";
import { useAdminTableState } from "@/components/data-table/useAdminTableState";
import { useAdminTableData } from "@/components/data-table/useAdminTableData";
import { useAdminTable } from "@/components/data-table/useAdminTable";
import { useTablePreferences } from "@/components/data-table/useTablePreferences";
import { useTableScrollBox } from "@/components/data-table/useTableScrollBox";
import { useVirtualBody } from "@/components/data-table/useVirtualBody";
import { cn } from "@/lib/utils";

const DEFAULT_PAGE_SIZE_OPTIONS = [10, 15, 25, 50, 100];

/**
 * `remembered` with this page's selected rows added (or their data refreshed)
 * and every deselected id dropped; the same map when nothing changed.
 */
function rememberSelection<TData>(
  remembered: ReadonlyMap<string, TData>,
  pageRows: Row<TData>[],
  rowSelection: Record<string, boolean>
): ReadonlyMap<string, TData> {
  let next: Map<string, TData> | null = null;
  for (const row of pageRows) {
    if (row.getIsSelected() && remembered.get(row.id) !== row.original) {
      next ??= new Map(remembered);
      next.set(row.id, row.original);
    }
  }
  for (const id of remembered.keys()) {
    if (!rowSelection[id]) {
      next ??= new Map(remembered);
      next.delete(id);
    }
  }
  return next ?? remembered;
}

/**
 * The admin list table: toolbar, sticky header, virtualised body, footer.
 *
 * This file is the orchestrator — state, the table instance and the body's
 * rows. Everything with a seam of its own lives next to it: the URL state
 * (`useAdminTableState`), the two data modes (`useAdminTableData`), column
 * geometry (`column-layout`), the cells (`head-cell`, `body-cells`) and the
 * chrome (`AdminTableToolbar`, `AdminTableMobileList`, the `DataPagination` footer).
 */
export function DataTable<TData>({
  queryKey,
  queryFn,
  rows,
  isLoading = false,
  columns,
  searchPlaceholder,
  emptyMessage,
  onRowClick,
  onRowDoubleClick,
  commands,
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
  groupBy,
  columnsStorageKey,
  paging = "pages",
  rowUnit = "rows",
  cellAlign = "middle",
  toolbar,
  summary,
  inspectorId,
  onPageRowsChange,
  renderMobileCard,
  framed = true,
}: Readonly<DataTableProps<TData>>) {
  const t = useTranslations("kitTable.dataTableExtra");
  const tTable = useTranslations("kitTable.table");
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
  const [toolbarRef, narrowToolbar] = useNarrowToolbar();

  const { data, clientRows, isInitialLoading, isRefreshing } = useAdminTableData({
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
  // Reported from the query's result, not from inside `queryFn`: a page served
  // from the cache never runs the fetch, and the screen's inspector would be
  // left holding the rows of whatever page was fetched last.
  const reportPageRows = useEffectEvent((page: typeof data) => onPageRowsChange?.(page.results, page));
  useEffect(() => {
    if (!isClientMode) reportPageRows(data);
  }, [isClientMode, data]);

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
  // Adjusted during render: the map only changes when the selection or a
  // selected row's data does, so the re-render it triggers settles at once.
  const [rememberedSelection, setRememberedSelection] = useState<ReadonlyMap<string, TData>>(() => new Map());
  const selection = rememberSelection(rememberedSelection, pageRows, rowSelection);
  if (selection !== rememberedSelection) setRememberedSelection(selection);
  const selectedData = [...selection.values()];
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

  const hasRowAction = Boolean(onRowClick || onRowDoubleClick);
  const hasLeadingColumn = Boolean(enableRowSelection || renderExpanded);
  const visibleLeafColumns = table.getVisibleLeafColumns();
  // Resizing commits once, on release (`columnResizeMode: "onEnd"`); mid-drag
  // the width lives in `columnSizingInfo`. Folding it in redraws the columns
  // as the handle moves, the same way TanStack will commit them.
  const { columnSizingStart, deltaPercentage } = table.getState().columnSizingInfo;
  const liveColumnSizing = useMemo(() => {
    if (deltaPercentage === null) return columnSizing;
    const live = { ...columnSizing };
    for (const [id, size] of columnSizingStart) live[id] = size + size * deltaPercentage;
    return live;
  }, [columnSizing, columnSizingStart, deltaPercentage]);
  // The body rows are memoised and compare it by identity.
  const layout = useMemo(
    () =>
      buildColumnLayout({ visibleColumns: visibleLeafColumns, columns, columnSizing: liveColumnSizing, hasLeadingColumn, density }),
    [visibleLeafColumns, columns, liveColumnSizing, hasLeadingColumn, density]
  );
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
  // Only the two rows whose `tabbable` flips repaint when focus moves.
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

  // The memoised rows all hold this one object for the table's lifetime; it
  // forwards to whichever handlers the latest render made.
  const latestRef = useRef({ handleRowClick, handleRowDoubleClick, gestures });
  // Refreshed after commit, before any event can reach a row.
  useLayoutEffect(() => {
    latestRef.current = { handleRowClick, handleRowDoubleClick, gestures };
  });
  const [rowHandlers] = useState<RowHandlers<TData>>(() => ({
    click: (event, row) => latestRef.current.handleRowClick(event, row),
    doubleClick: (event, row) => latestRef.current.handleRowDoubleClick(event, row),
    focus: setFocusedRowId,
    pointerDown: (event, row) => latestRef.current.gestures.rowPointerDown(row)(event),
    checkboxPointerDown: (event, row) => latestRef.current.gestures.checkboxPointerDown(row)(event),
    checkboxClick: (event) => latestRef.current.gestures.checkboxClick(event)
  }));

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
  // Only cells left on TanStack's default renderer get search highlighting.
  const customCellIds = useMemo(
    () => new Set(columns.filter((column) => column.cell !== undefined).map(columnDefId)),
    [columns]
  );
  const sharedRowProps: SharedRowProps<TData> = {
    layout,
    cellPadding: density === "compact" ? "py-1" : "py-2.5",
    cellAlign,
    search: debouncedSearchValue,
    customCellIds,
    hasLeadingColumn,
    enableRowSelection: Boolean(enableRowSelection),
    hasExpandedDetail: Boolean(renderExpanded),
    hasRowAction,
    rowHintId,
    handlers: rowHandlers
  };
  const bodyItemContext = {
    shared: sharedRowProps,
    inspectorId,
    tabbableRowId,
    renderExpanded,
    measureElement: virtualizer.measureElement
  };

  /**
   * The built-in search box stays unless a `toolbar` was handed in without a
   * `searchPlaceholder`: that is a screen whose server does not search.
   */
  const showSearch = searchPlaceholder !== undefined || toolbar === undefined;
  const searchLabel = searchPlaceholder ?? t("search");
  const resolvedEmptyMessage = emptyMessage ?? t("noRecords");

  const emptyState = (
    <AdminTableEmptyState
      message={resolvedEmptyMessage}
      hasSearch={Boolean(searchValue)}
      hasFilters={Boolean(serializedFilters)}
      onClear={() => { setSearchValue(""); setFilters({}); }}
    />
  );

  const offPageSelected = selectedData.length - selectedOnPage;
  const clearSelection = () => setRowSelection({});

  return (
    <Card
      ref={cardRef}
      variant="flat"
      className={cn(
        "overflow-hidden",
        framed ? "border-border/50 bg-card/50" : "admin-table-unframed rounded-none border-0 bg-transparent"
      )}
    >
      <AdminTableToolbar
        ref={toolbarRef}
        narrow={narrowToolbar}
        showSearch={showSearch}
        searchInputId={searchInputId}
        searchLabel={searchLabel}
        searchValue={searchValue}
        onSearchChange={setSearchValue}
        filters={toolbar}
        isRefreshing={isRefreshing}
        commands={(commands ?? []).filter((command) => !command.hidden)}
        view={{
          selectedCount: selectedData.length,
          onExportCsv: exportCsv,
          canExport: pageRows.length > 0,
          // Cards have no row density.
          density: isMobile ? undefined : density,
          onToggleDensity: () => setDensity(density === "compact" ? "comfortable" : "compact"),
          prefsKey,
          visibility,
          onVisibilityChange: setVisibility,
          // A phone's cards are built from the first visible columns, so the picker stays there only
          // while no `renderMobileCard` replaces them.
          pickerColumns: columnsStorageKey && !(isMobile && renderMobileCard) ? pickerColumns : undefined,
          onToggleColumn: toggleColumn,
          onResetColumns: resetToDefaults,
          groupBy
        }}
      />

      {/* ── TABLE ───────────────────────────────────────── */}
      <div>
        <p id={rowHintId} className="sr-only">
          {t("rowHint", { select: enableRowSelection ? "yes" : "no", open: onRowClick ? "yes" : "no" })}
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
          <AdminRowContextMenu table={table} rowActions={rowActions}>
          <TableBody onKeyDown={handleBodyKeyDown}>
            {bodyItems.length === 0 && isInitialLoading ? (
              // The first load draws rows, not "nothing here": the empty
              // state is a fact about the data, and there is no data yet.
              Array.from({ length: 5 }, (_, index) => (
                <TableRow key={`skeleton-${index}`} aria-hidden>
                  {Array.from({ length: bodyColumnCount }, (_, cell) => (
                    <TableCell key={cell} className="py-3">
                      <Skeleton className="h-4 w-3/4" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : bodyItems.length === 0 ? (
              // Not a row: right-click keeps the browser's menu instead of the row menu.
              <TableRow onContextMenu={(event) => event.stopPropagation()}>
                <TableCell colSpan={bodyColumnCount} className="py-8 text-center">
                  {emptyState}
                </TableCell>
              </TableRow>
            ) : virtualize ? (
              <>
                {padTop > 0 ? <tr aria-hidden style={{ height: padTop }} /> : null}
                {virtualItems.map((virtual) => renderBodyItem(bodyItems[virtual.index], bodyItemContext, virtual))}
                {padBottom > 0 ? <tr aria-hidden style={{ height: padBottom }} /> : null}
              </>
            ) : (
              bodyItems.map((item) => renderBodyItem(item, bodyItemContext))
            )}
            {safeTotal > 0 && isInfinite ? (
              // Inside the scroll box, where the sentinel is only in view once
              // the user has actually reached the bottom of the loaded rows.
              <TableRow className="hover:bg-transparent" onContextMenu={(event) => event.stopPropagation()}>
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
          </AdminRowContextMenu>
        </Table>
        )}
      </div>

      {safeTotal > 0 && !isInfinite && !showAll ? (
        <DataPagination
          page={currentPage}
          totalPages={totalPageCount}
          onPageChange={setCurrentPage}
          className="border-t border-border/40 px-4 py-2"
          // One page: the count and the page size stay (a larger page is how a
          // reader gets back a split list); only the pager goes.
          leading={
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="tabular-nums">{tTable("range", { start: rangeStart, end: rangeEnd, total: safeTotal })}</span>
              <div className="flex items-center gap-1.5">
                <span>{tTable("rows")}</span>
                <Select
                  value={String(effectivePageSize)}
                  onValueChange={(value) => {
                    setCurrentPage(1);
                    setPageSize(Number(value));
                  }}
                >
                  <SelectTrigger aria-label={tTable("rowsPerPage")} size="sm" className="w-auto gap-1 px-2.5 tabular-nums">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {availablePageSizeOptions.map((option) => (
                      <SelectItem key={option} value={String(option)} className="tabular-nums">
                        {option}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {summary ? <span>{summary}</span> : null}
            </div>
          }
        />
      ) : summary ? (
        <div className="border-t border-border/40 px-4 py-2 text-label text-[color:var(--aqt-fg-dim)]">{summary}</div>
      ) : null}

      {bulkActions && selectedData.length > 0 ? (
        <BulkBar count={selectedData.length} offPage={offPageSelected} onClear={clearSelection}>
          {bulkActions(selectedData, clearSelection)}
        </BulkBar>
      ) : null}
    </Card>
  );
}
