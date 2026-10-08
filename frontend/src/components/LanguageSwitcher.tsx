"use client";

import { useId } from "react";
import { useTranslations, useLocale } from "next-intl";
import { useRouter } from "next/navigation";

import { EYEBROW_CLASS } from "@/components/kit/tone";
import {
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem
} from "@/components/ui/dropdown-menu";
import { setUserLocale } from "@/i18n/locale-actions";
import type { Locale } from "@/i18n/resolve-locale";
import { cn } from "@/lib/utils";

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
 * The language choice inside a dropdown menu: real `menuitemradio` rows, so it
 * joins the menu's arrow-key navigation (a plain button inside `role="menu"`
 * is unreachable — Radix blocks Tab there). Selecting keeps the menu open so
 * the re-rendered labels confirm the switch.
 */
export function LanguageMenuRadioGroup() {
  const t = useTranslations();
  const labelId = useId();
  const { active, switchTo } = useLocaleSwitch();

  return (
    <>
      <DropdownMenuLabel id={labelId} className={EYEBROW_CLASS}>
        {t("common.language")}
      </DropdownMenuLabel>
      <DropdownMenuRadioGroup
        aria-labelledby={labelId}
        value={active}
        onValueChange={(next) => switchTo(next as Locale)}
      >
        {ORDER.map((loc) => (
          <DropdownMenuRadioItem key={loc} value={loc} lang={loc} onSelect={(e) => e.preventDefault()}>
            {LANGUAGE_NAME[loc]}
          </DropdownMenuRadioItem>
        ))}
      </DropdownMenuRadioGroup>
    </>
  );
}

/**
 * The segmented RU | EN control. Both languages are always visible (no toggle
 * ambiguity) and the active one carries the accent. Uses `--aqt-*` tokens.
 */
export default function LanguageSwitcher({ className }: Readonly<{ className?: string }>) {
  const t = useTranslations();
  const { active, switchTo } = useLocaleSwitch();

  return (
    <div
      role="group"
      aria-label={t("common.switchLanguage")}
      className={cn(
        "inline-flex h-9 items-center rounded-[9px] border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] p-[3px]",
        className
      )}
    >
      {ORDER.map((loc) => {
        const isActive = loc === active;
        return (
          <button
            key={loc}
            type="button"
            onClick={() => switchTo(loc)}
            aria-pressed={isActive}
            // The visible code leads the name (WCAG 2.5.3: "click RU" must
            // work for voice control); the endonym follows for screen readers.
            aria-label={`${loc.toUpperCase()} — ${LANGUAGE_NAME[loc]}`}
            lang={loc}
            className={cn(
              "aqt-tnum flex h-full min-w-9 items-center justify-center rounded-md px-1 text-label font-bold uppercase tracking-[0.06em] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
              isActive
                ? "bg-[color:color-mix(in_srgb,var(--aqt-teal)_14%,transparent)] text-[color:var(--aqt-teal)]"
                : "text-[color:var(--aqt-fg-dim)] hover:text-[color:var(--aqt-fg)]"
            )}
          >
            {loc}
          </button>
        );
      })}
    </div>
  );
}
