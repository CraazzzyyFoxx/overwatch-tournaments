"use client";

import type { ReactNode } from "react";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useQueryParams } from "@/hooks/useQueryParams";
import { cn } from "@/lib/utils";

type ViewSegmentOption<V extends string> = {
  value: V;
  label: ReactNode;
  /** Optional accessible name when `label` is an icon. */
  ariaLabel?: string;
};

export type ViewSegmentProps<V extends string> = {
  /** URL parameter this segment writes; `view` for section views, `tab` for sub-tabs. */
  param: string;
  options: readonly ViewSegmentOption<V>[];
  /** Value in effect when the URL carries none (the default is never written). */
  defaultValue: V;
  /** Called after the URL changes, for a secondary store such as `localStorage`. */
  onChange?: (value: V) => void;
  label: string;
  /** Hidden below `sm` — narrow screens get the default view only. */
  hideOnMobile?: boolean;
  className?: string;
};

/**
 * A switch between views of one section, bound to a URL parameter. The default
 * value is never written, so the canonical URL stays clean and a link with no
 * `?view=` means "the default".
 *
 * Visually it is the site's one segmented control — `ToggleGroup` in the `pill`
 * variant — so every toolbar's search, sort and view switch share one 32px row.
 */
export function ViewSegment<V extends string>({
  param,
  options,
  defaultValue,
  onChange,
  label,
  hideOnMobile = true,
  className
}: Readonly<ViewSegmentProps<V>>) {
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const raw = searchParams?.get(param);
  const current = (options.find((o) => o.value === raw)?.value ?? defaultValue) as V;

  return (
    <ToggleGroup
      value={current}
      onValueChange={(value) => {
        const next = options.find((o) => o.value === value)?.value;
        if (!next) return;
        setParams({ [param]: next === defaultValue ? null : next });
        onChange?.(next);
      }}
      aria-label={label}
      variant="pill"
      size="sm"
      className={cn(hideOnMobile && "hidden sm:flex", className)}
    >
      {options.map((option) => (
        <ToggleGroupItem key={option.value} value={option.value}>
          {option.ariaLabel ? <span className="sr-only">{option.ariaLabel}</span> : null}
          <span aria-hidden={option.ariaLabel ? true : undefined}>{option.label}</span>
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

/** Read the current value of a `ViewSegment` param outside the component. */
export function readViewParam<V extends string>(
  searchParams: { get(name: string): string | null } | null,
  param: string,
  options: readonly V[],
  defaultValue: V
): V {
  const raw = searchParams?.get(param);
  return (options as readonly string[]).includes(raw ?? "") ? (raw as V) : defaultValue;
}
