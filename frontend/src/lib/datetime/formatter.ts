import { createFormatter, type Locale } from "next-intl";

import type { Formatter } from ".";

// One formatter (and its Intl constructor cache) per locale × zone, shared by
// every component: a table of 500 dated rows must not build 500 of them.
const formatters = new Map<string, Formatter>();

/** The formatter behind both `useFormatter` and `getFormatter`. */
export function formatterFor(locale: string, timeZone: string | undefined): Formatter {
  const key = `${locale}|${timeZone ?? ""}`;
  let formatter = formatters.get(key);
  if (!formatter) {
    // `Locale` is typed as the UI languages ("en" | "ru"); the regional
    // variant is still one of them as far as messages are concerned.
    formatter = createFormatter({ locale: locale as Locale, timeZone });
    formatters.set(key, formatter);
  }
  return formatter;
}
