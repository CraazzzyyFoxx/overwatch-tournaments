"use client";

import * as React from "react";

import { outlineSurfaceClass } from "@/components/ui/button";
import { StatusDot } from "@/components/ui/status-dot";
import { TONE_HUE, TONE_TINT } from "@/components/ui/tone";
import { cn } from "@/lib/utils";

export interface FilterChipProps extends Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  "type"
> {
  /** Whether this chip's filter is currently applied. Drives `aria-pressed`. */
  active?: boolean;
  /** Optional trailing count (e.g. how many rows match this filter). */
  count?: number | string | null;
  /** Optional leading dot colour token, e.g. `var(--aqt-rose)` for "live". */
  dotColor?: string;
  /**
   * Colour of the active state, replacing teal: a CSS colour or token such as
   * a role's tint (`var(--role-tank)`, `hsl(…)`). The chip derives its fill,
   * border and text from it, so a set of role filters reads as their roles.
   */
  accent?: string;
}

/**
 * Fixed 32px, not padding-derived: the row's search, select and segment are
 * `h-8` too, and a count badge must not make one chip taller than the rest.
 */
const CHIP_CLASS =
  "inline-flex h-8 shrink-0 cursor-pointer items-center gap-2 rounded-lg px-3 text-caption font-medium transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50";

/**
 * The single filter chip for the whole site: a real `<button>` with
 * `aria-pressed`, so Enter/Space work and assistive technology reads which
 * filter is on.
 *
 * At rest it wears the outline button's surface (`outlineSurfaceClass`): a chip
 * is pressed, so it sits raised beside the buttons and select triggers of its
 * row, not sunk like the search field. On, it takes the tone tint over teal or
 * `accent`. `data-slot` is the hook a page-scoped stylesheet sizes it by.
 */
export const FilterChip = React.forwardRef<HTMLButtonElement, FilterChipProps>(
  ({ active = false, count, dotColor, accent, className, style, children, ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      aria-pressed={active}
      data-slot="filter-chip"
      className={cn(
        CHIP_CLASS,
        active
          ? cn("border", TONE_TINT, accent ? undefined : TONE_HUE.accent)
          : cn(
              outlineSurfaceClass,
              "disabled:hover:border-[color:var(--aqt-border-2)] disabled:hover:bg-[color:var(--aqt-overlay-3)]"
            ),
        className
      )}
      style={accent ? ({ "--tone-hue": accent, ...style } as React.CSSProperties) : style}
      {...props}
    >
      {dotColor ? <StatusDot style={{ color: dotColor }} /> : null}
      {children}
      {count !== undefined && count !== null ? (
        <span
          data-slot="filter-chip-count"
          className={cn(
            "rounded-sm px-1.5 py-px font-[family-name:var(--aqt-data)] text-label",
            active
              ? "bg-[color:color-mix(in_srgb,var(--tone-hue)_16%,transparent)] text-[color:var(--tone-hue)]"
              : "bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg-faint)]"
          )}
        >
          {count}
        </span>
      ) : null}
    </button>
  )
);
FilterChip.displayName = "FilterChip";

/**
 * Lays chips out in one wrapping row and exposes them as one labelled group,
 * so a screen reader announces "Filters, group" once rather than a bare run of
 * buttons.
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
    <div role="group" aria-label={label} className={cn("flex flex-wrap items-center gap-2", className)}>
      {children}
    </div>
  );
}
