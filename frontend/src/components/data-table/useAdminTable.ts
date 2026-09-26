"use client";

import React, { useState } from "react";
import {
  ColumnFiltersState,
  ColumnOrderState,
  ColumnSizingState,
  OnChangeFn,
  RowSelectionState,
  SortingState,
  getCoreRowModel,
  getExpandedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable
} from "@tanstack/react-table";

import { columnDefId } from "@/components/data-table/columns";
import { readAdminColumnFilter, type AdminTableFilters } from "@/components/data-table/filters";
import type { AdminDataTableProps } from "@/components/data-table/types";

export interface AdminTableOptions<TData>
  extends Pick<AdminDataTableProps<TData>, "columns" | "getRowId" | "enableRowSelection" | "renderExpanded"> {
  data: TData[];
  isClientMode: boolean;
  /** Client mode `all`: one page big enough to hold every row. */
  showAll: boolean;
  /** Client mode `infinite`: one page that grows by a batch at a time. */
  isInfinite: boolean;
  rowCount: number;
  page: number;
  pageSize: number;
  setCurrentPage: (page: number) => void;
  setPageSize: (pageSize: number) => void;
  filters: AdminTableFilters;
  sorting: SortingState;
  setSorting: OnChangeFn<SortingState>;
  columnSizing: ColumnSizingState;
  setColumnSizing: OnChangeFn<ColumnSizingState>;
  columnOrder: ColumnOrderState;
  visibility: Record<string, boolean>;
}

/**
 * The TanStack table instance, wired to whichever mode the caller asked for:
 * client mode runs the filter/sort/pagination row models locally, server mode
 * marks all three manual and reports the page it was handed.
 */
export function useAdminTable<TData>({
  columns,
  data,
  getRowId,
  enableRowSelection,
  renderExpanded,
  isClientMode,
  showAll,
  isInfinite,
  rowCount,
  page,
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
}: AdminTableOptions<TData>) {
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  // Header filters are query params in server mode and TanStack column filters
  // in client mode, keyed by the column that declared them.
  const columnFilters: ColumnFiltersState = isClientMode
    ? columns.flatMap((column) => {
        const spec = readAdminColumnFilter(column.meta);
        if (!spec) return [];
        const values = filters[spec.param];
        if (!values?.length) return [];
        const id = columnDefId(column);
        return id ? [{ id, value: values }] : [];
      })
    : [];

  // Infinite scrolling renders one page that grows: `page` still counts the
  // batches loaded, so `?page=` restores the same depth after a reload.
  // `all` is one page big enough to hold every row the data can yield.
  const paginationState = showAll
    ? { pageIndex: 0, pageSize: Math.max(data.length, 1) }
    : isInfinite
      ? { pageIndex: 0, pageSize: page * pageSize }
      : { pageIndex: page - 1, pageSize };

  const table = useReactTable<TData>({
    data,
    columns,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: isClientMode ? getFilteredRowModel() : undefined,
    getSortedRowModel: isClientMode ? getSortedRowModel() : undefined,
    getPaginationRowModel: isClientMode ? getPaginationRowModel() : undefined,
    getExpandedRowModel: renderExpanded ? getExpandedRowModel() : undefined,
    getRowCanExpand: renderExpanded ? () => true : undefined,
    enableRowSelection: enableRowSelection,
    // Shift+click stacks sorts in client mode; server mode takes one column.
    enableMultiSort: isClientMode,
    isMultiSortEvent: (event) => (event as React.MouseEvent).shiftKey,
    enableColumnResizing: true,
    // One write per drag rather than one per pointer move: sizing is persisted.
    columnResizeMode: "onEnd",
    onColumnSizingChange: setColumnSizing,
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    // Pagination is controlled by this component's own page state, so TanStack
    // must be told where every page change goes — a controlled `state.pagination`
    // with no handler leaves its internal copy free to drift, and its
    // auto-reset then fights this component's state on every render.
    onPaginationChange: isClientMode
      ? (updater) => {
          const next =
            typeof updater === "function"
              ? updater(paginationState)
              : updater;
          setCurrentPage(next.pageIndex + 1);
          setPageSize(next.pageSize);
        }
      : undefined,
    autoResetPageIndex: false,
    state: {
      sorting,
      rowSelection,
      columnSizing,
      columnOrder,
      columnVisibility: visibility,
      ...(isClientMode
        ? { columnFilters, pagination: paginationState }
        : {})
    },
    manualPagination: !isClientMode,
    manualSorting: !isClientMode,
    manualFiltering: !isClientMode,
    rowCount: isClientMode ? undefined : rowCount,
  });

  return { table, rowSelection, setRowSelection };
}
