"use client";

import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/components/data-table/host";

/** Page numbers around the current one, with the first and last always reachable. */
const MAX_VISIBLE_PAGES = 5;

export interface AdminTablePaginationProps {
  total: number;
  rangeStart: number;
  rangeEnd: number;
  currentPage: number;
  totalPageCount: number;
  onPageChange: (page: number) => void;
  pageSize: number;
  pageSizeOptions: number[];
  onPageSizeChange: (pageSize: number) => void;
}

/** The row under the table: how much is shown, rows per page, page numbers. */
export function AdminTablePagination({
  total,
  rangeStart,
  rangeEnd,
  currentPage,
  totalPageCount,
  onPageChange,
  pageSize,
  pageSizeOptions,
  onPageSizeChange
}: Readonly<AdminTablePaginationProps>) {
  const pageButton = (page: number) => (
    <button
      key={page}
      type="button"
      onClick={() => onPageChange(page)}
      aria-label={`Page ${page}`}
      aria-current={currentPage === page ? "page" : undefined}
      className={cn(
        "flex size-7 items-center justify-center rounded-md text-xs tabular-nums transition-colors",
        currentPage === page
          ? "bg-primary text-primary-foreground font-medium"
          : "text-muted-foreground hover:bg-accent/30 hover:text-foreground",
      )}
    >
      {page}
    </button>
  );

  const gap = (key: string) => (
    <span key={key} aria-hidden className="flex size-7 items-center justify-center text-xs text-muted-foreground">…</span>
  );

  const pages: React.ReactNode[] = [];
  if (totalPageCount <= MAX_VISIBLE_PAGES) {
    for (let page = 1; page <= totalPageCount; page++) pages.push(pageButton(page));
  } else {
    pages.push(pageButton(1));
    if (currentPage > 3) pages.push(gap("gap-start"));
    const start = Math.max(2, currentPage - 1);
    const end = Math.min(totalPageCount - 1, currentPage + 1);
    for (let page = start; page <= end; page++) pages.push(pageButton(page));
    if (currentPage < totalPageCount - 2) pages.push(gap("gap-end"));
    pages.push(pageButton(totalPageCount));
  }

  return (
    <div className="flex items-center justify-between gap-3 border-t border-border/40 px-4 py-2">
      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        <span className="tabular-nums">{rangeStart}–{rangeEnd} of {total}</span>
        <div className="flex items-center gap-1.5">
          <span>Rows</span>
          <Select value={String(pageSize)} onValueChange={(v) => onPageSizeChange(Number(v))}>
            <SelectTrigger aria-label="Rows per page" className="h-8 w-auto gap-1 border-border bg-muted/30 px-2.5 text-sm tabular-nums text-muted-foreground">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {pageSizeOptions.map((opt) => (
                <SelectItem key={opt} value={String(opt)} className="text-xs tabular-nums">{opt}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="flex items-center gap-1">
        <button
          onClick={() => onPageChange(Math.max(currentPage - 1, 1))}
          disabled={currentPage <= 1}
          className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent/30 hover:text-foreground disabled:opacity-30 disabled:pointer-events-none"
          aria-label="Previous page"
        >
          <ChevronLeft aria-hidden className="size-4" />
        </button>

        {pages}

        <button
          onClick={() => onPageChange(Math.min(currentPage + 1, totalPageCount))}
          disabled={currentPage >= totalPageCount}
          className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent/30 hover:text-foreground disabled:opacity-30 disabled:pointer-events-none"
          aria-label="Next page"
        >
          <ChevronRight aria-hidden className="size-4" />
        </button>
      </div>
    </div>
  );
}
