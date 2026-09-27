"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import styles from "../TournamentDetail.module.css";

/**
 * The bracket's own horizontal scroll owner.
 *
 * A grid item defaults to `min-width: auto`, so without this the bracket's
 * intrinsic width grew the page and the whole document scrolled sideways.
 * `<section>` plus an accessible name IS the region — no explicit `role` — and
 * `tabIndex` makes the scroll container reachable by keyboard, which a
 * scrollable box otherwise is not.
 */
export function BracketScroller({ children }: Readonly<{ children: ReactNode }>) {
  const t = useTranslations();

  return (
    <section
      aria-label={t("tournamentDetail.bracketRegion")}
      tabIndex={0}
      className={styles.bracketScroller}
    >
      {children}
    </section>
  );
}
