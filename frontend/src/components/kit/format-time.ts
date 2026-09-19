import type { DateTimeFormatOptions } from "next-intl";

/**
 * Shared date/duration formatting for every admin collector dashboard (rank,
 * subscriptions, streams) — each domain used to carry its own copy.
 */

/**
 * The slice of next-intl's formatter the admin date helpers need.
 *
 * Plain modules cannot call `useFormatter()`, and a module-level
 * `Intl.DateTimeFormat` would have to pin a locale — which is how half the
 * admin area came to print `en-US` dates inside the `ru` default UI. So the
 * helpers take the formatter instead: client components pass `useFormatter()`,
 * server components `await getFormatter()`. Both satisfy this shape.
 */
export interface AdminDateFormatter {
  dateTime: (value: Date, options?: DateTimeFormatOptions) => string;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

/** Compact "5m ago" / "2h ago" style relative time; falls back to "—". */
export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const diffSec = Math.round((Date.now() - date.getTime()) / 1000);
  if (diffSec < 60) return "just now";
  const mins = Math.round(diffSec / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** Compact "60s" / "5m" / "2h" rendering of a seconds-based interval setting. */
export function formatInterval(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600}h`;
  if (seconds % 60 === 0) return `${seconds / 60}m`;
  return `${seconds}s`;
}
