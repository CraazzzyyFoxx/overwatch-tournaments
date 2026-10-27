"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

/**
 * The bracket's own horizontal scroll owner.
 *
 * A grid item defaults to `min-width: auto`, so without this the bracket's
 * intrinsic width grew the page and the whole document scrolled sideways.
 * `<section>` plus an accessible name IS the region — no explicit `role` — and
 * `tabIndex` makes the scroll container reachable by keyboard, which a
 * scrollable box otherwise is not. Deliberately no `contain`/`transform` here:
 * the bracket's fullscreen mode is `position: fixed` and a containment
 * ancestor would clip it.
 */
export function BracketScroller({ children }: Readonly<{ children: ReactNode }>) {
  const t = useTranslations();

  return (
    <section
      aria-label={t("tournamentDetail.bracketRegion")}
      tabIndex={0}
      className="min-w-0 max-w-full overflow-x-auto overscroll-x-contain [scrollbar-width:thin] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      {children}
    </section>
  );
}
