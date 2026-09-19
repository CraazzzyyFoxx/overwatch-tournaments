import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";
import { IntlErrorCode } from "next-intl";

import { resolveLocale } from "./resolve-locale";
import { pickMessages, ZONES, type Zone } from "./zones";

export default getRequestConfig(async () => {
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()]);
  const locale = resolveLocale(
    cookieStore.get("NEXT_LOCALE")?.value,
    headerStore.get("accept-language"),
  );
  // Never trust the header: middleware sets it, the gateway strips any inbound
  // copy, and an unrecognised value falls back to the widest public bundle
  // rather than to nothing.
  const header = headerStore.get("x-owt-zone");
  const zone: Zone = ZONES.find((candidate) => candidate === header) ?? "web";
  // Runtime-selected specifier: the locale comes from a cookie / Accept-Language,
  // so this cannot be a static import.
  const all = (await import(`./messages/${locale}.json`)).default;
  const messages = pickMessages(all, zone);

  return {
    locale,
    messages,
    onError(error) {
      if (error.code !== IntlErrorCode.MISSING_MESSAGE) {
        console.error(error);
        return;
      }
      // A missing message used to be silent ("expected during rollout"). Now it
      // is also the single failure mode of the zone split: a namespace left out
      // of this request's bundle renders its dotted key to the user. Silent in
      // production (a log line per render is not worth it), loud everywhere a
      // developer or CI would see it, with the zone named so the fix is obvious.
      if (process.env.NODE_ENV !== "production") {
        console.warn(`[i18n] missing message in zone "${zone}": ${error.message}`);
      }
    },
    getMessageFallback({ namespace, key }) {
      // Preserve the previous behavior: render the dotted key when a message
      // is missing instead of throwing.
      return [namespace, key].filter(Boolean).join(".");
    },
  };
});
