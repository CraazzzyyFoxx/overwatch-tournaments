"use client";

import React from "react";
import { useTranslations, useLocale } from "next-intl";
import { useRouter } from "next/navigation";

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

// Segment width in px — the sliding pill translates by this per index.
const SEGMENT_W = 36;

/**
 * Editorial Tactical language switcher: a segmented RU | EN control. Both
 * languages are always visible (no toggle ambiguity), and a teal pill slides to
 * the active one. Uses the global `--aqt-*` tokens (defined on :root, so it also
 * renders correctly inside the UserMenu dropdown portal).
 */
export default function LanguageSwitcher({ className }: { className?: string }) {
  const t = useTranslations();
  const active = useLocale() as Locale;
  const router = useRouter();

  const switchTo = (next: Locale) => {
    if (next === active) return;
    void setUserLocale(next).then(() => router.refresh());
  };

  const activeIndex = Math.max(0, ORDER.indexOf(active));

  return (
    <div
      role="group"
      aria-label={t("common.switchLanguage")}
      className={cn(
        "relative inline-flex h-8 items-center rounded-[var(--aqt-radius-sm)] border border-[var(--aqt-border)] bg-[var(--aqt-card)] p-[3px]",
        className
      )}
    >
      {/* Sliding teal pill — the memorable anchor; marks the active language. */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-[3px] left-[3px] w-9 rounded-[calc(var(--aqt-radius-sm)-3px)] bg-[hsl(174_72%_46%/0.12)] ring-1 ring-inset ring-[hsl(174_72%_46%/0.35)] transition-transform duration-200 ease-out motion-reduce:transition-none"
        style={{ transform: `translateX(${activeIndex * SEGMENT_W}px)` }}
      />
      {ORDER.map((loc) => {
        const isActive = loc === active;
        return (
          <button
            key={loc}
            type="button"
            onClick={() => switchTo(loc)}
            aria-pressed={isActive}
            aria-label={LANGUAGE_NAME[loc]}
            className={cn(
              "aqt-mono relative z-10 flex h-full w-9 items-center justify-center rounded-[calc(var(--aqt-radius-sm)-3px)] text-[11px] font-semibold uppercase tracking-wide outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[var(--aqt-teal)]",
              isActive
                ? "text-[var(--aqt-teal)]"
                : "text-[var(--aqt-fg-muted)] hover:text-[var(--aqt-fg)]"
            )}
          >
            {loc}
          </button>
        );
      })}
    </div>
  );
}
