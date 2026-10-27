"use client";

import * as React from "react";
import { Search } from "lucide-react";

import { eyebrowClass } from "@/components/ui/eyebrow";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type SearchFieldBaseProps = Omit<
  React.ComponentPropsWithoutRef<typeof Input>,
  "type" | "onChange" | "value" | "defaultValue"
> & {
  /**
   * Accessible name. Required: a placeholder is never a label — it disappears
   * the moment the user types.
   */
  label: string;
  /** Render the label visibly above the field instead of only for AT. */
  showLabel?: boolean;
  containerClassName?: string;
};

export type SearchFieldProps = SearchFieldBaseProps &
  (
    | {
        value: string;
        onValueChange: (value: string) => void;
        defaultValue?: never;
        onChange?: never;
      }
    /** Uncontrolled: the caller owns the DOM value through `ref` (e.g. a debounced, URL-backed search). */
    | {
        defaultValue?: string;
        onChange: React.ChangeEventHandler<HTMLInputElement>;
        value?: never;
        onValueChange?: never;
      }
  );

/**
 * The single search input for the public site: an `Input` (its surface, focus,
 * disabled and error states, the iOS 16px rule) with a magnifier inside it and
 * a required accessible name. `size` defaults to `sm`, the 32px toolbar row
 * shared with `SelectTrigger` and the segmented `ToggleGroup`.
 */
export const SearchField = React.forwardRef<HTMLInputElement, SearchFieldProps>(
  (
    {
      value,
      onValueChange,
      onChange,
      label,
      showLabel = false,
      size = "sm",
      className,
      containerClassName,
      id,
      ...props
    },
    ref
  ) => {
    const reactId = React.useId();
    const inputId = id ?? `search-${reactId}`;

    return (
      <div className={cn("relative", containerClassName)}>
        <label
          htmlFor={inputId}
          className={showLabel ? cn(eyebrowClass("dim"), "mb-1.5 block") : "sr-only"}
        >
          {label}
        </label>
        <div className="relative">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]"
          />
          <Input
            ref={ref}
            id={inputId}
            type="search"
            size={size}
            value={value}
            onChange={onValueChange ? (event) => onValueChange(event.target.value) : onChange}
            className={cn("pl-8", className)}
            {...props}
          />
        </div>
      </div>
    );
  }
);
SearchField.displayName = "SearchField";
