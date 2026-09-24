"use client";

import * as React from "react";
import { Search } from "lucide-react";

import { cn } from "@/lib/utils";

export interface SearchFieldProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type" | "onChange" | "value"> {
  value: string;
  onValueChange: (value: string) => void;
  /**
   * Accessible name. Required: a placeholder is never a label — it disappears
   * the moment the user types.
   */
  label: string;
  /** Render the label visibly above the field instead of only for AT. */
  showLabel?: boolean;
  containerClassName?: string;
}

/**
 * The single search input for the public site.
 *
 * Replaces seven hand-rolled inputs that each shipped `outline-none` with no
 * replacement ring, no accessible name, a hand-inlined magnifier SVG, and a
 * 13px font size that makes iOS Safari zoom the page on focus.
 *
 * - `text-base sm:text-sm` keeps mobile at 16px (no iOS zoom) while desktop
 *   stays at the project's compact density.
 * - `focus-visible:` gives keyboard users a real indicator.
 * - `h-8` pins the toolbar row height shared with `SelectTrigger` and the
 *   segmented `ToggleGroup`; padding-derived height drifted to 34/38px.
 * - The icon is `lucide-react`'s `Search` at `currentColor`, matching the icon
 *   set used everywhere else.
 */
export const SearchField = React.forwardRef<HTMLInputElement, SearchFieldProps>(
  (
    { value, onValueChange, label, showLabel = false, className, containerClassName, id, ...props },
    ref
  ) => {
    const reactId = React.useId();
    const inputId = id ?? `search-${reactId}`;

    return (
      <div className={cn("relative", containerClassName)}>
        <label
          htmlFor={inputId}
          className={cn(
            showLabel
              ? "mb-1.5 block text-label font-medium uppercase tracking-wide text-[color:var(--aqt-fg-dim)]"
              : "sr-only"
          )}
        >
          {label}
        </label>
        <div className="relative">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]"
          />
          <input
            ref={ref}
            id={inputId}
            type="search"
            value={value}
            onChange={(event) => onValueChange(event.target.value)}
            className={cn(
              "h-8 w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] pl-8 pr-3",
              "text-base text-[color:var(--aqt-fg)] placeholder:text-[color:var(--aqt-fg-faint)] sm:text-sm",
              "outline-none transition-colors",
              "focus-visible:border-[color:var(--aqt-teal)] focus-visible:ring-2 focus-visible:ring-[color:color-mix(in_srgb,var(--aqt-teal)_25%,transparent)]",
              className
            )}
            {...props}
          />
        </div>
      </div>
    );
  }
);
SearchField.displayName = "SearchField";
