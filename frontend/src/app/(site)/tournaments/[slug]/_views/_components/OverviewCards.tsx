"use client";

import { ArrowRight } from "lucide-react";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * One section of the overview: a heading, then its content. Open by default,
 * per DESIGN §5 — a page section is a heading and what it heads; only a dense
 * data block (a table, match rows, the podium) is `framed`, and then only the
 * block, never the heading with it.
 *
 * `size`: `title` in the main column and the full-width bands; `heading` in
 * the narrow reference column, where a 22px heading would outweigh the 15px
 * facts under it.
 *
 * Deliberately no `overflow: hidden`: the mini-bracket scrolls horizontally
 * inside its own block, and `#phases` must stay scrollable-to.
 */
export function OverviewSection({
  title,
  action,
  id,
  size = "title",
  framed = false,
  className,
  children
}: Readonly<{
  title?: string;
  action?: React.ReactNode;
  id?: string;
  size?: "title" | "heading";
  framed?: boolean;
  className?: string;
  children: React.ReactNode;
}>) {
  return (
    <section className={cn("min-w-0 scroll-mt-28", className)} id={id}>
      {title || action ? (
        <div
          className={cn(
            "flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1",
            size === "title" ? "mb-3" : "mb-2.5"
          )}
        >
          {title ? (
            <h2
              className={cn(
                "font-onest font-semibold text-[color:var(--aqt-fg)]",
                size === "title" ? "text-title" : "text-heading"
              )}
            >
              {title}
            </h2>
          ) : (
            <span />
          )}
          {action}
        </div>
      ) : null}
      {framed ? (
        <Card className="min-w-0 p-4">
          {children}
        </Card>
      ) : (
        children
      )}
    </section>
  );
}

/** "All matches →": where a section continues, beside its heading. */
export function SectionLink({ href, children }: Readonly<{ href: string; children: React.ReactNode }>) {
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
 * The two columns under the overview's full-width lead: the phase's own story
 * on the left, the reference that stays the same all tournament long on the
 * right (format, links). The reference column is one quiet stack split by
 * hairlines, not a pile of cards. Below `lg` the story comes first.
 */
export function OverviewColumns({
  main,
  aside
}: Readonly<{ main: React.ReactNode; aside: React.ReactNode }>) {
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] lg:gap-10">
      <div className="grid min-w-0 content-start gap-8">{main}</div>
      <div className="grid min-w-0 content-start divide-y divide-[color:var(--aqt-border)] [&>*:first-child]:pt-0 [&>*:last-child]:pb-0 [&>*]:py-5">
        {aside}
      </div>
    </div>
  );
}
