export const LOCALES = ["en", "ru"] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "ru";

function isLocale(value: string | undefined): value is Locale {
  return value === "en" || value === "ru";
}

/**
 * Resolve the active locale on the server.
 *
 * Order of precedence: a valid `NEXT_LOCALE` cookie → the primary
 * `Accept-Language` tag → the default `ru`. This mirrors the previous
 * client-side behavior (`browserLang === "ru" ? "ru" : "en"`): when a browser
 * language is known, Russian speakers get `ru` and everyone else gets `en`;
 * only when no language hint exists at all do we fall back to the ru-first
 * default. Computed during the request so `<html lang>` and SSR output are
 * correct with no language flash.
 */
export function resolveLocale(
  cookieValue: string | undefined,
  acceptLanguage: string | null,
): Locale {
  if (isLocale(cookieValue)) return cookieValue;

  const primary = acceptLanguage
    ?.split(",")[0]
    ?.trim()
    .split("-")[0]
    ?.toLowerCase();

  // No language hint at all → ru-first default.
  if (!primary) return DEFAULT_LOCALE;

  // A known browser language: Russian → ru, anything else → en.
  return primary === "ru" ? "ru" : "en";
}
