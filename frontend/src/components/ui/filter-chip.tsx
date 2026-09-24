"use client";

import * as React from "react";

import { StatusDot } from "@/components/ui/status-dot";
import { cn } from "@/lib/utils";

export interface FilterChipProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "type"> {
  /** Whether this chip's filter is currently applied. Drives `aria-pressed`. */
  active?: boolean;
  /** Optional trailing count (e.g. how many rows match this filter). */
  count?: number | string | null;
  /** Optional leading dot colour token, e.g. `var(--aqt-rose)` for "live". */
  dotColor?: string;
}

/**
 * The single filter chip for the whole public site.
 *
 * It is a real `<button>` with `aria-pressed`, so Enter/Space work and assistive
 * technology can read which filter is on. Every previous call site was a
 * `<span role="button" tabIndex={0} onClick>` — focusable but not activatable by
 * keyboard, and silent about its state.
 *
 * Styling stays on the existing `.aqt-filter-chip` global class so the visual
 * language does not change; only the semantics and the focus ring do.
 */
export const FilterChip = React.forwardRef<HTMLButtonElement, FilterChipProps>(
  ({ active = false, count, dotColor, className, children, ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      aria-pressed={active}
      className={cn("aqt-filter-chip", active && "active", className)}
      {...props}
    >
      {dotColor ? <StatusDot style={{ color: dotColor }} /> : null}
      {children}
      {count !== undefined && count !== null ? (
        <span className="aqt-count">{count}</span>
      ) : null}
    </button>
  )
);
FilterChip.displayName = "FilterChip";

/**
 * Wrapper that lays chips out with the shared `.aqt-filters` rhythm and exposes
 * them as one labelled group, so a screen reader announces "Filters, group"
 * once rather than a bare run of buttons.
 */
export function FilterChipGroup({
  label,
  className,
  children
}: Readonly<{
  label: string;
  className?: string;
  children: React.ReactNode;
}>) {
  return (
    <div role="group" aria-label={label} className={cn("aqt-filters", className)}>
      {children}
    </div>
  );
}
