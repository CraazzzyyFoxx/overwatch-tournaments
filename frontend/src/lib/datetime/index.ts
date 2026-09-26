import type { createFormatter } from "next-intl";

import { DEFAULT_WORKSPACE_TIMEZONE } from "@/lib/workspace/timezone";

/**
 * The app's date/number formatter: next-intl's, bound to the viewer's zone and
 * regional format. Get it from `useFormatter()` (`@/lib/datetime/client`) or
 * `await getFormatter()` (`@/lib/datetime/server`) — never from next-intl
 * directly, which knows only the UI language and the request config's zone.
 *
 * This module stays free of runtime next-intl imports, so the pure helpers
 * below load anywhere — including under a test's partial `next-intl` mock.
 */
export type Formatter = ReturnType<typeof createFormatter>;

/** Carries the browser's IANA zone to the server, so SSR already prints local time. */
export const TIME_ZONE_COOKIE = "NEXT_TIMEZONE";

/**
 * The zone every date is printed in: the viewer's, once the browser has
 * reported it (`DateTimeProvider` writes the cookie). Before that — the very
 * first response — the workspace default, which is what most of the audience
 * lives in anyway. The cookie value is returned verbatim, not canonicalised:
 * the provider compares it with the browser's own spelling.
 */
export function resolveTimeZone(cookieValue: string | undefined): string {
  if (!cookieValue) return DEFAULT_WORKSPACE_TIMEZONE;
  try {
    new Intl.DateTimeFormat("en", { timeZone: cookieValue });
    return cookieValue;
  } catch {
    return DEFAULT_WORKSPACE_TIMEZONE;
  }
}

/**
 * The locale dates are formatted in: the UI language, in the viewer's own
 * conventions, read from their primary `Accept-Language` tag.
 *
 *  - Same language → their exact variant: `en-GB` gets "22 Sept, 10:00",
 *    `en-US` keeps "Sep 22, 10:00 AM".
 *  - Another language (a `ru` browser on the English UI) → the UI language with
 *    the viewer's 24-hour clock: "Sep 22, 10:00". Only ever towards 24h: a
 *    12-hour viewer does not push AM/PM into Russian.
 *
 * Messages keep the plain UI locale — this string only reaches `Intl`.
 */
export function resolveFormatLocale(
  uiLocale: string,
  acceptLanguage: string | null | undefined
): string {
  const tag = acceptLanguage?.split(",")[0]?.split(";")[0]?.trim();
  if (!tag) return uiLocale;
  let viewer: Intl.Locale;
  try {
    viewer = new Intl.Locale(tag);
  } catch {
    return uiLocale; // "*" or garbage
  }
  if (viewer.language === uiLocale) return viewer.baseName;
  const { hourCycle } = new Intl.DateTimeFormat(viewer.baseName, {
    hour: "numeric"
  }).resolvedOptions();
  return hourCycle === "h23" ? `${uiLocale}-u-hc-h23` : uiLocale;
}

/**
 * Inclusive calendar-day range: "Jan 15 – 20, 2026" / "15–20 янв. 2026 г.".
 *
 * Tournament days are stored as UTC midnights, so they are read in UTC — in the
 * viewer's zone everyone west of Greenwich would see each tournament start a
 * day early. `formatRange` collapses the shared month/year itself.
 */
export function formatDateRange(
  format: Pick<Formatter, "dateTimeRange">,
  start: Date | string,
  end: Date | string
): string {
  return format.dateTimeRange(new Date(start), new Date(end), {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC"
  });
}
