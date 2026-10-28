"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

export interface SortableColumn<R> {
  key: string;
  label: string;
  title?: string;
  /** Absent: the column does not sort. `null` values sort last either way. */
  sortValue?: (row: R) => number | string | null;
  /** The first click sorts ascending (smaller is better: a place, deaths, a pick number). */
  ascendingFirst?: boolean;
  numeric?: boolean;
  cell: (row: R) => ReactNode;
}

export interface TableSort {
  key: string;
  ascending: boolean;
}

/**
 * A plain sortable table: a real button in each sortable `th`, `aria-sort` on the active one. With `pageSize` it shows
 * that many rows and loads more as its end scrolls near; sorting and the caller's filters still run over every row.
 * `stickyFirst`: below `sm` the place column goes and the first column (the row's name) stays put while the numbers
 * scroll under it.
 */
export function SortableTable<R>({
  rows,
  columns,
  rowKey,
  defaultSort,
  label,
  empty,
  pageSize,
  stickyFirst = false
}: Readonly<{
  rows: readonly R[];
  columns: readonly SortableColumn<R>[];
  rowKey: (row: R) => string | number;
  defaultSort: TableSort;
  label: string;
  empty: string;
  pageSize?: number;
  stickyFirst?: boolean;
}>) {
  const t = useTranslations("tournamentDetail");
  const [sort, setSort] = useState<TableSort>(defaultSort);
  const [limit, setLimit] = useState(pageSize ?? Infinity);
  const sorted = useMemo(() => {
    const column = columns.find((item) => item.key === sort.key);
    if (!column?.sortValue) return rows;
    const value = column.sortValue;
    return [...rows].sort((a, b) => {
      const left = value(a);
      const right = value(b);
      if (left == null || right == null) return left == null ? (right == null ? 0 : 1) : -1;
      const order =
        typeof left === "string" ? left.localeCompare(String(right)) : left - (right as number);
      return sort.ascending ? order : -order;
    });
  }, [rows, columns, sort]);

  const shown = sorted.slice(0, limit);
  const rest = sorted.length - shown.length;

  // The next page loads as the end of the table nears the viewport; the button stays for keyboards and old browsers.
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = sentinel.current;
    if (!node || !pageSize || rest <= 0) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) setLimit((current) => current + pageSize);
      },
      { rootMargin: "0px 0px 400px 0px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [pageSize, rest]);

  // The edges sit on the card's own padding.
  const edge = (index: number) =>
    cn(
      index === 0 &&
        stickyFirst &&
        "max-sm:sticky max-sm:left-0 max-sm:z-10 max-sm:border-r max-sm:border-[color:var(--aqt-border)] max-sm:bg-card max-sm:pl-4.5",
      index === columns.length - 1 && "pr-4.5"
    );
  const place = cn("w-12 pl-4.5 text-right", stickyFirst && "max-sm:hidden");

  return (
    <>
      <Table aria-label={label}>
        <TableHeader>
          <TableRow>
            <TableHead scope="col" className={place}>
              #
            </TableHead>
            {columns.map((column, index) => {
              const active = sort.key === column.key;
              const arrow = active ? (
                sort.ascending ? (
                  <ArrowUp aria-hidden />
                ) : (
                  <ArrowDown aria-hidden />
                )
              ) : null;
              return (
                <TableHead
                  key={column.key}
                  scope="col"
                  title={column.title}
                  aria-sort={
                    column.sortValue
                      ? active
                        ? sort.ascending
                          ? "ascending"
                          : "descending"
                        : "none"
                      : undefined
                  }
                  className={cn(column.numeric && "text-right", edge(index))}
                >
                  {column.sortValue ? (
                    <Button
                      variant="ghost"
                      size="label"
                      onClick={() =>
                        setSort(
                          active
                            ? { key: column.key, ascending: !sort.ascending }
                            : { key: column.key, ascending: column.ascendingFirst === true }
                        )
                      }
                      className={cn(
                        "hover:bg-transparent hover:text-[color:var(--aqt-fg)]",
                        column.numeric ? "justify-end" : "justify-start",
                        active && "text-[color:var(--aqt-teal)]"
                      )}
                    >
                      {/* A right-aligned label keeps its edge on the numbers' edge: the arrow goes before it. */}
                      {column.numeric ? arrow : null}
                      {column.label}
                      {column.numeric ? null : arrow}
                    </Button>
                  ) : (
                    column.label
                  )}
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={columns.length + 1}
                className="py-8 text-center text-[color:var(--aqt-fg-dim)]"
              >
                {empty}
              </TableCell>
            </TableRow>
          ) : (
            shown.map((row, rowIndex) => (
              <TableRow key={rowKey(row)}>
                <TableCell className={cn(place, "aqt-tnum text-[color:var(--aqt-fg-faint)]")}>
                  {rowIndex + 1}
                </TableCell>
                {columns.map((column, index) => (
                  <TableCell
                    key={column.key}
                    className={cn(column.numeric && "aqt-tnum text-right", edge(index))}
                  >
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      {rest > 0 && pageSize ? (
        <div
          ref={sentinel}
          className="flex justify-center border-t border-[color:var(--aqt-border)] px-4.5 py-2.5"
        >
          <Button variant="ghost" size="sm" onClick={() => setLimit(limit + pageSize)}>
            {t("common.showMore", { count: Math.min(pageSize, rest) })}
          </Button>
        </div>
      ) : null}
    </>
  );
}
