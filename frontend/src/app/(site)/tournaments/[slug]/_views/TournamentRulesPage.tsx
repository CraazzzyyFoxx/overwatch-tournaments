"use client";

import { useTranslations } from "next-intl";
import { useMemo } from "react";

import { Markdown } from "@/components/Markdown";
import { extractToc } from "@/lib/markdown-toc";
import { cn } from "@/lib/utils";

import { RulesToc, useActiveSection } from "../_components/RulesToc";
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
  const rules = tournament?.rules?.trim();
  // One entry is not a table of contents, it is a duplicate of the heading the
  // reader can already see — and a document written with bold lead-ins instead
  // of `##` produces none at all. Both fall back to the plain single column.
  //
  // Above the early return, with the observer, because hooks cannot run
  // conditionally — and memoised so the parse does not re-run (and the
  // observer does not tear down) on every unrelated render.
  const toc = useMemo(() => (rules ? extractToc(rules) : []), [rules]);
  const [activeId, markSection] = useActiveSection(toc);
  const hasToc = toc.length > 1;

  // The shell owns pending and error for this exact payload and renders its
  // children only once it resolved, so there is no third state to show here.
  if (!tournament) return null;

  return (
    <section className={styles.publicDataPage} aria-label={t("common.rules")}>
      {rules ? (
        // No card: a regulation is a page of prose, and boxing it adds a border
        // around text that nothing else on the page is competing with. Tables
        // inside still scroll on their own.
        //
        // 48rem — one step WIDER than the 42rem `/docs` and `/terms` read at,
        // chosen deliberately so the document fills more of a desktop tab.
        // Measured in Inter at 18px: 768px ≈ 80 Cyrillic characters per line,
        // above the 75 every readability guide draws the limit at. The price is
        // paid in line tracking on the widest viewports; `leading-relaxed`
        // (1.625) on every paragraph is what keeps that survivable, so do not
        // tighten it here.
        <div
          className={cn(
            "grid justify-center gap-8",
            // The rail takes the empty left gutter a centred column leaves
            // behind; the PAIR is centred, so the document does not drift right
            // as the viewport grows. Below `xl` there is no gutter to take, so
            // the rail becomes a collapsed summary above the text instead.
            hasToc && "xl:grid-cols-[16rem_minmax(0,48rem)]"
          )}
        >
          {hasToc ? (
            <>
              <details className="w-full max-w-3xl rounded-lg border border-border px-4 py-3 xl:hidden">
                <summary className="cursor-pointer text-body font-semibold text-foreground">
                  {t("tournamentDetail.rules.toc")}
                </summary>
                <RulesToc entries={toc} activeId={activeId} onJump={markSection} className="pt-2" />
              </details>
              <aside className="hidden xl:block">
                {/* `top-28` is the same offset the tournament pages' anchors
                    already use (`scroll-mt-28`), so the rail clears the sticky
                    tab bar by exactly as much as a jumped-to heading does. */}
                <RulesToc
                  entries={toc}
                  activeId={activeId}
                  onJump={markSection}
                  // A regulation with twenty sections must not push its own
                  // rail off the screen: the rail scrolls inside the viewport
                  // it is pinned to.
                  className="sticky top-28 max-h-[calc(100dvh-9rem)] overflow-y-auto"
                />
              </aside>
            </>
          ) : null}
          <Markdown source={rules} className="w-full max-w-3xl py-2" />
        </div>
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
