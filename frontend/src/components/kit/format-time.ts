import type { DateTimeFormatOptions } from "next-intl";

import type { Formatter } from "@/lib/datetime";

/**
 * Shared date/duration formatting for every admin collector dashboard (rank,
 * subscriptions, streams) — each domain used to carry its own copy.
 */

/**
 * The slice of the app formatter the admin date helpers need.
 *
 * Plain modules cannot call `useFormatter()`, and a module-level
 * `Intl.DateTimeFormat` would have to pin a locale — which is how half the
 * admin area came to print `en-US` dates inside the `ru` default UI. So the
 * helpers take the formatter instead: client components pass `useFormatter()`
 * from `@/lib/datetime/client`, server components `await getFormatter()` from
 * `@/lib/datetime/server`. Both satisfy this shape.
 */
export interface DateFormatter {
  dateTime: (value: Date, options?: DateTimeFormatOptions) => string;
}

export function formatDate(format: DateFormatter, value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : format.dateTime(date, { dateStyle: "medium", timeStyle: "short" });
}

/** Compact "5 min. ago" / "5 мин. назад" in the UI language; falls back to "—". */
export function formatRelative(
  format: Pick<Formatter, "relativeTime">,
  value: string | null | undefined,
  now: number = Date.now()
): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return format.relativeTime(date, { now, style: "short" });
}

/** Compact "60s" / "5m" / "2h" rendering of a seconds-based interval setting. */
export function formatInterval(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600}h`;
  if (seconds % 60 === 0) return `${seconds / 60}m`;
  return `${seconds}s`;
}
