"use client";

import { useTranslations, useLocale } from "next-intl";
import { useRouter } from "next/navigation";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { setUserLocale } from "@/i18n/locale-actions";
import type { Locale } from "@/i18n/resolve-locale";

// RU first — the platform's ru-first audience and default locale.
const ORDER = ["ru", "en"] as const satisfies readonly Locale[];

// Endonyms: a language is always named in its own language, never translated.
const LANGUAGE_NAME: Record<Locale, string> = {
  ru: "Русский",
  en: "English"
};

function useLocaleSwitch() {
  const active = useLocale() as Locale;
  const router = useRouter();

  const switchTo = (next: Locale) => {
    if (next === active) return;
    void setUserLocale(next).then(() => router.refresh());
  };

  return { active, switchTo };
}

/**
 * The segmented RU | EN control. Both languages are always visible (no toggle
 * ambiguity) and the active one carries the accent.
 */
export default function LanguageSwitcher({ className }: Readonly<{ className?: string }>) {
  const t = useTranslations();
  const { active, switchTo } = useLocaleSwitch();

  return (
    <ToggleGroup
      variant="pill"
      value={active}
      onValueChange={(next) => switchTo(next as Locale)}
      aria-label={t("common.switchLanguage")}
      className={className}
    >
      {ORDER.map((loc) => (
        <ToggleGroupItem
          key={loc}
          value={loc}
          // The visible code leads the name (WCAG 2.5.3: "click RU" must
          // work for voice control); the endonym follows for screen readers.
          aria-label={`${loc.toUpperCase()} — ${LANGUAGE_NAME[loc]}`}
          lang={loc}
        >
          {loc.toUpperCase()}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
