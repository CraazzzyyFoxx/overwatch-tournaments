import { getLocale, getTimeZone } from "next-intl/server";
import { headers } from "next/headers";

import { resolveFormatLocale, type Formatter } from ".";
import { formatterFor } from "./formatter";

/** The request's format locale — see `resolveFormatLocale`. */
export async function getFormatLocale(): Promise<string> {
  const [locale, headerStore] = await Promise.all([getLocale(), headers()]);
  return resolveFormatLocale(locale, headerStore.get("accept-language"));
}

/** Server-component twin of `useFormatter` from `@/lib/datetime/client`. */
export async function getFormatter(): Promise<Formatter> {
  const [locale, timeZone] = await Promise.all([getFormatLocale(), getTimeZone()]);
  return formatterFor(locale, timeZone);
}
