"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Windowed page list: first, last, the current page and one neighbour each
 * side, with `null` marking an elision. Replaces three ad-hoc versions — one
 * that rendered *every* page (unbounded flex row, guaranteed overflow) and one
 * that rendered only pages 1–3 (so past page 3 no button was ever marked
 * current and mid-range pages were unreachable in one click).
 */
export function buildPageWindow(current: number, total: number): (number | null)[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);

  // Always keep the first and last page reachable, plus a three-wide window
  // around the current one, widened at the ends so the control never shrinks
  // below five numeric targets.
  const start = Math.min(Math.max(current - 1, 2), total - 4);
  const window = [1, start, start + 1, start + 2, start + 3, total];

  const out: (number | null)[] = [];
  let prev = 0;
  for (const page of window) {
    if (page <= prev || page < 1 || page > total) continue;
    if (prev && page - prev > 1) out.push(null);
    out.push(page);
    prev = page;
  }
  return out;
}

interface DataPaginationProps {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  className?: string;
  /**
   * Content before the page buttons: a "Showing 1–20 of 340" range, a
   * rows-per-page select. Set in the muted label style, and kept when there is
   * only one page.
   */
  leading?: React.ReactNode;
}

const PAGE_BUTTON_CLASS = "aqt-tnum min-w-8 px-2";

/**
 * The single pagination control for the site and the admin tables. Replaces
 * six implementations that between them lost `aria-label` on the arrows,
 * `aria-current` on the active page, and used bare `‹`/`›`/`←`/`→` glyphs
 * (which screen readers read literally) instead of icons.
 */
export function DataPagination({
  page,
  totalPages,
  onPageChange,
  className,
  leading
}: Readonly<DataPaginationProps>) {
  const t = useTranslations();

  const hasControls = totalPages > 1;
  if (!hasControls && !leading) return null;

  // One shell for both branches. These used to diverge: with a single page the
  // component returned a bare `<div className={className}>{summary}</div>`, so
  // the summary lost the size and muted color it gets alongside the page
  // buttons and rendered as full-size default text flush against the card edge.
  const Shell = hasControls ? "nav" : "div";
  const safePage = Math.min(Math.max(page, 1), totalPages);
  const pageWindow = hasControls ? buildPageWindow(safePage, totalPages) : [];

  return (
    <Shell
      aria-label={hasControls ? t("common.pagination.label") : undefined}
      className={cn("flex flex-wrap items-center gap-3", className)}
    >
      {leading ? <div className="text-label text-[color:var(--aqt-fg-dim)]">{leading}</div> : null}
      {hasControls ? (
        <div className="ms-auto flex flex-wrap items-center gap-1.5">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className={PAGE_BUTTON_CLASS}
            disabled={safePage <= 1}
            aria-label={t("common.pagination.previous")}
            onClick={() => onPageChange(safePage - 1)}
          >
            <ChevronLeft aria-hidden />
          </Button>

          {pageWindow.map((entry, index) =>
            entry === null ? (
              <span
                key={`gap-${index}`}
                aria-hidden
                className="px-1 text-caption text-[color:var(--aqt-fg-faint)]"
              >
                &hellip;
              </span>
            ) : (
              <Button
                key={entry}
                type="button"
                variant={entry === safePage ? "accent" : "outline"}
                size="sm"
                aria-current={entry === safePage ? "page" : undefined}
                aria-label={t("common.pagination.goToPage", { page: entry })}
                className={PAGE_BUTTON_CLASS}
                onClick={() => onPageChange(entry)}
              >
                {entry}
              </Button>
            )
          )}

          <Button
            type="button"
            variant="outline"
            size="sm"
            className={PAGE_BUTTON_CLASS}
            disabled={safePage >= totalPages}
            aria-label={t("common.pagination.next")}
            onClick={() => onPageChange(safePage + 1)}
          >
            <ChevronRight aria-hidden />
          </Button>
        </div>
      ) : null}
    </Shell>
  );
}
