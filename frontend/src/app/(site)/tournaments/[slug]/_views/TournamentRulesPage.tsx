"use client";

import { useTranslations } from "next-intl";

import { Markdown } from "@/components/Markdown";
import { Card, CardContent } from "@/components/ui/card";

import { TournamentPageState } from "../_components/TournamentPageState";
import { useTournamentQuery } from "../_hooks/useTournamentClientData";
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
        <Card>
          {/* A measure cap, not a layout: prose set to the full width of a
              desktop card runs past the ~75-character line every readability
              guide draws the limit at. Tables inside scroll on their own. */}
          <CardContent className="pt-6">
            <Markdown source={rules} className="max-w-[72ch]" />
          </CardContent>
        </Card>
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
