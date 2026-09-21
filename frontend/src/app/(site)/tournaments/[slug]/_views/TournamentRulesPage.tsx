"use client";

import { useTranslations } from "next-intl";

import { Markdown } from "@/components/Markdown";

import { TournamentPageState } from "../_components/TournamentPageState";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import styles from "../TournamentDetail.module.css";

/**
 * The organizer's published regulations — format, code of conduct, tiebreakers.
 *
 * No read of its own: `rules` rides in the page-shell payload
 * (`getPublicOverview` asks for the entity), which is also what decides whether
 * this tab exists at all. One source for the tab and its content means the rail
 * can never offer a Rules tab that then renders nothing.
 *
 * The section carries no visible heading: the rail already names it, and the
 * document's own `#` heading is its title — a second one above it would be the
 * word "Rules" twice. Same treatment as the Maps section.
 */
export default function TournamentRulesPage({ slug }: Readonly<{ slug: string }>) {
  const t = useTranslations();
  const tournament = useTournamentQuery(slug).data;
  // The shell owns pending and error for this exact payload and renders its
  // children only once it resolved, so there is no third state to show here.
  if (!tournament) return null;

  const rules = tournament.rules?.trim();

  return (
    <section className={styles.publicDataPage} aria-label={t("common.rules")}>
      {rules ? (
        // No card: a regulation is a page of prose, and boxing it adds a border
        // around text that nothing else on the page is competing with. The
        // measure cap is the only layout it needs. Tables inside still scroll
        // on their own.
        //
        // 48rem — one step WIDER than the 42rem `/docs` and `/terms` read at,
        // chosen deliberately so the document fills more of a desktop tab.
        // Measured in Inter at 16px: 768px ≈ 89 Cyrillic characters per line,
        // above the 75 every readability guide draws the limit at. The price is
        // paid in line tracking on the widest viewports; `leading-relaxed`
        // (1.625) on every paragraph is what keeps that survivable, so do not
        // tighten it here.
        //
        // Centred, because the cap cannot be spent instead: on a wide desktop
        // the column still leaves the tab's sides empty, and empty space on ONE
        // side reads as a layout that broke rather than a document that ends.
        <Markdown source={rules} className="mx-auto max-w-3xl py-2" />
      ) : (
        // Reachable by a direct link after an organizer clears the document:
        // the tab is gone from the rail, the URL still resolves.
        <TournamentPageState
          state="empty"
          title={t("tournamentDetail.rules.emptyTitle")}
          description={t("tournamentDetail.rules.emptyDescription")}
        />
      )}
    </section>
  );
}
