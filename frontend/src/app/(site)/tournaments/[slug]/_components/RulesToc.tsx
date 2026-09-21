"use client";

import { useTranslations } from "next-intl";

import type { TocEntry } from "@/lib/markdown-toc";
import { cn } from "@/lib/utils";

/**
 * Section list for the published regulations.
 *
 * Plain anchors, no scroll handler: the browser already knows how to reach an
 * `id`, it survives being opened in a new tab, and the URL a reader copies
 * points at the section they were on.
 */
export function RulesToc({
  entries,
  className
}: Readonly<{ entries: TocEntry[]; className?: string }>) {
  const t = useTranslations();

  return (
    <nav aria-label={t("tournamentDetail.rules.toc")} className={cn("text-body", className)}>
      <ol className="border-l border-border">
        {entries.map((entry, index) => (
          // Index in the key, not the id alone: two sections may share a title,
          // and React needs the pair to stay unique even when the anchor does
          // not (see `slugifyHeading`).
          <li key={`${entry.id}-${index}`}>
            <a
              href={`#${entry.id}`}
              className={cn(
                "block border-l-2 border-transparent py-1 pr-2 text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground",
                entry.level === 3 ? "pl-7 text-caption" : "pl-4"
              )}
            >
              {entry.text}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
