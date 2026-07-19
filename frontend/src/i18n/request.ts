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
  const messages = (await import(`./messages/${locale}.json`)).default;

  return {
    locale,
    messages,
    onError(error) {
      // Missing translations are expected during rollout — don't spam the logs.
      // Anything else indicates a real bug and should surface.
      if (error.code !== IntlErrorCode.MISSING_MESSAGE) {
        console.error(error);
      }
    },
    getMessageFallback({ namespace, key }) {
      // Preserve the previous behavior: render the dotted key when a message
      // is missing instead of throwing.
      return [namespace, key].filter(Boolean).join(".");
    },
  };
});
