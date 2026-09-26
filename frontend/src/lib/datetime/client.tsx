"use client";

import { useLocale, useTimeZone } from "next-intl";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, type ReactNode } from "react";

import { TIME_ZONE_COOKIE, type Formatter } from ".";
import { formatterFor } from "./formatter";

const FormatLocaleContext = createContext<string | null>(null);

/**
 * Mounted once, in the root layout, inside the root `ZoneIntlProvider`.
 *
 * Carries the server-resolved format locale (`resolveFormatLocale`) to client
 * formatters — the same string the server used, so hydration agrees — and
 * teaches the server the viewer's zone: when the browser's differs from the
 * one the page was rendered in, it is stored in `TIME_ZONE_COOKIE` and the
 * route re-rendered. That happens once per browser (and again after travel);
 * a browser refusing the cookie keeps the default zone, without a refresh loop,
 * because the effect only re-runs when the rendered zone changes.
 */
export function DateTimeProvider({
  formatLocale,
  children
}: Readonly<{ formatLocale: string; children: ReactNode }>) {
  const timeZone = useTimeZone();
  const router = useRouter();

  useEffect(() => {
    const local = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!local || local === timeZone) return;
    document.cookie = `${TIME_ZONE_COOKIE}=${local}; path=/; max-age=31536000; samesite=lax`;
    router.refresh();
  }, [timeZone, router]);

  return (
    <FormatLocaleContext.Provider value={formatLocale}>{children}</FormatLocaleContext.Provider>
  );
}

/**
 * Drop-in for next-intl's `useFormatter`, in the viewer's zone and regional
 * format. Outside `DateTimeProvider` (tests) it formats in the plain UI locale.
 */
export function useFormatter(): Formatter {
  const uiLocale = useLocale();
  const timeZone = useTimeZone();
  const formatLocale = useContext(FormatLocaleContext);
  return formatterFor(formatLocale ?? uiLocale, timeZone);
}
