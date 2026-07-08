"use client";

import { useTranslations, useLocale } from "next-intl";
import { useRouter } from "next/navigation";

import { setUserLocale } from "./locale-actions";
import type { Locale } from "./resolve-locale";

export type { Locale };

/**
 * Backwards-compatible shim over next-intl.
 *
 * The previous hand-rolled i18n exposed `{ t, locale, setLocale }` with a
 * loosely-typed `t(key, variables)`. Many call-sites build keys dynamically
 * (e.g. `t(\`analytics.glossary.${kind}.label\`)`), which next-intl's strictly
 * typed `t` would reject at compile time. This shim keeps the original loose
 * contract so all existing call-sites work unchanged during the migration.
 *
 * Removed in Phase 4 once every call-site uses `useTranslations`/`useLocale`
 * from next-intl directly.
 */
export function useTranslation() {
  const translate = useTranslations();
  const locale = useLocale() as Locale;
  const router = useRouter();

  const t = translate as unknown as (
    key: string,
    variables?: Record<string, string | number>,
  ) => string;

  const setLocale = (next: Locale) => {
    void setUserLocale(next).then(() => router.refresh());
  };

  return { t, locale, setLocale };
}
