"use client";

import { createContext, useContext, type ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { CardSurface } from "@/components/profile/atoms";
import { Eyebrow } from "@/components/ui/eyebrow";
import { cn } from "@/lib/utils";

/**
 * Every `OverviewSection` is a profile-style card (`CardSurface`); under `OverviewInlineSections` it is a labelled
 * block INSIDE such a card instead (an eyebrow, not a second heading).
 */
const InlineContext = createContext(false);

export function OverviewInlineSections({ children }: Readonly<{ children: ReactNode }>) {
  return <InlineContext.Provider value>{children}</InlineContext.Provider>;
}

/**
 * One block of the tournament's views: a card with a heading and, beside it, where the block continues.
 *
 * Deliberately no `overflow: hidden`: the mini-bracket scrolls horizontally
 * inside its own block, and `#phases` must stay scrollable-to.
 */
export function OverviewSection({
  title,
  action,
  id,
  className,
  children
}: Readonly<{
  title?: string;
  action?: ReactNode;
  id?: string;
  className?: string;
  children: ReactNode;
}>) {
  const inline = useContext(InlineContext);
  return (
    // A card section is a flex column, so the stretch `CardColumns` gives the section reaches its card.
    <section className={cn("min-w-0 scroll-mt-28", !inline && "flex flex-col", className)} id={id}>
      {inline ? (
        <>
          {title ? (
            <Eyebrow as="h3" className="mb-2 block">
              {title}
            </Eyebrow>
          ) : null}
          {children}
        </>
      ) : (
        <CardSurface title={title} action={action} className="flex-1">
          {children}
        </CardSurface>
      )}
    </section>
  );
}

/** "All matches →": where a section continues, beside its heading. */
export function SectionLink({ href, children }: Readonly<{ href: string; children: ReactNode }>) {
  return (
    <HoverPrefetchLink
      href={href}
      className="inline-flex items-center gap-1 text-caption font-medium text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-teal)]"
    >
      {children}
      <ArrowRight aria-hidden className="size-3.5" />
    </HoverPrefetchLink>
  );
}

/**
 * The page's two columns, ending on one line: from `lg` each column is a flex stack whose last card grows to the
 * other column's bottom. Cards must be the direct children. `even` splits 1:1, the default is the 2:1 main/side split.
 */
export function CardColumns({
  main,
  side,
  even = false
}: Readonly<{ main: ReactNode; side: ReactNode; even?: boolean }>) {
  const column = "flex min-w-0 flex-col gap-4 lg:[&>*:last-child]:flex-1";
  return (
    <div
      className={cn(
        "grid min-w-0 gap-4",
        even ? "lg:grid-cols-2" : "lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]"
      )}
    >
      <div className={column}>{main}</div>
      <div className={column}>{side}</div>
    </div>
  );
}

/** A card subtitle that explains rather than counts: below `sm` the title needs the row. */
export const wideOnly = (text: string) => <span className="hidden sm:inline">{text}</span>;

/** Description and links on the left, the format (and, before the start, the schedule) on the right. */
export function AboutTournamentCard({
  aboutCard,
  formatCard,
  linksCard,
  phasesCard
}: Readonly<{
  aboutCard: ReactNode;
  formatCard: ReactNode;
  linksCard: ReactNode;
  phasesCard?: ReactNode;
}>) {
  const t = useTranslations("tournamentDetail");
  return (
    <OverviewSection title={t("overview.reference.title")}>
      <OverviewInlineSections>
        {/* Columns per non-empty side: a tournament with no description or links gives the format the full row. */}
        <div className="grid gap-x-10 gap-y-6 md:auto-cols-fr md:grid-flow-col">
          <div className="grid content-start gap-6 empty:hidden">
            {aboutCard}
            {linksCard}
          </div>
          <div className="grid content-start gap-6">
            {phasesCard}
            {formatCard}
          </div>
        </div>
      </OverviewInlineSections>
    </OverviewSection>
  );
}
