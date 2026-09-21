import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";
import { IntlErrorCode } from "next-intl";

import { resolveLocale } from "./resolve-locale";

export default getRequestConfig(async () => {
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()]);
  const locale = resolveLocale(
    cookieStore.get("NEXT_LOCALE")?.value,
    headerStore.get("accept-language"),
  );
  // Runtime-selected specifier: the locale comes from a cookie / Accept-Language,
  // so this cannot be a static import.
  const messages = (await import(`./messages/${locale}.json`)).default;
  // The WHOLE tree, deliberately. Server rendering costs no payload for a
  // message it does not render, and `getTranslations` in any zone reads from
  // here. Narrowing happens where it is actually observable — at each
  // `NextIntlClientProvider`, which serialises its `messages` into the RSC
  // payload. See `src/i18n/zones.ts`.

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
      // of a zone bundle renders its dotted key to the user. Silent in
      // production (a log line per render is not worth it), loud everywhere a
      // developer or CI would see it.
      if (process.env.NODE_ENV !== "production") {
        console.warn(`[i18n] missing message: ${error.message}`);
      }
    },
    getMessageFallback({ namespace, key }) {
      // Preserve the previous behavior: render the dotted key when a message
      // is missing instead of throwing.
      return [namespace, key].filter(Boolean).join(".");
    },
  };
});
