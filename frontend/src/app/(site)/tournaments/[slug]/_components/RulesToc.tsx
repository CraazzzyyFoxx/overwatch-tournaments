"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";

import type { TocEntry } from "@/lib/markdown-toc";
import { cn } from "@/lib/utils";

/**
 * The offset every anchor on the tournament pages already scrolls to
 * (`scroll-mt-28` = 7rem). The observer's band starts below it for the same
 * reason the anchors do: the sticky rail covers everything above.
 */
const HEADER_OFFSET_PX = 112;

/**
 * Which section the reader is looking at, for the rail to mark.
 *
 * One observer for the whole page, driven from `TournamentRulesPage`, because
 * the rail is mounted twice (collapsed summary + sticky rail) and only CSS
 * decides which one is visible — two copies of the hook would mean two
 * observers watching the same headings.
 */
export function useActiveSection(entries: TocEntry[]): readonly [string | null, (id: string) => void] {
  // The ids as one string: the array is rebuilt on every render, so its
  // identity cannot be the effect's dependency, and its CONTENT is what
  // actually decides what to observe.
  const ids = entries.map((entry) => entry.id).join("\n");
  const [active, setActive] = useState<string | null>(null);
  // While a jump's smooth scroll is in flight, every frame it passes through
  // looks to the observer like a section the reader chose. The pin says
  // otherwise until the scroll lands.
  const pinnedUntil = useRef(0);

  const markSection = useCallback((id: string) => {
    pinnedUntil.current = Date.now() + 700;
    setActive(id);
  }, []);

  useEffect(() => {
    // happy-dom (the behaviour tests) has no IntersectionObserver, and neither
    // does a browser old enough to matter here — the rail still navigates, it
    // just stops marking where the reader is.
    if (typeof IntersectionObserver === "undefined") return;

    const order = ids ? ids.split("\n") : [];
    const targets = order
      .map((id) => document.getElementById(id))
      .filter((element) => element !== null);
    if (targets.length === 0) return;

    // The section being READ is the last heading that has already passed under
    // the header line — not the next one coming up the screen, which is what
    // "topmost heading currently on screen" would mark. Before the first
    // heading reaches the line (the position every reader starts at) the first
    // section owns the mark.
    const currentSection = () => {
      let current = order[0];
      for (const target of targets) {
        // Four pixels of slack: the callback is delivered a frame AFTER the
        // crossing, so a heading parked exactly on the line can read back as
        // 113 and lose its own mark.
        if (target.getBoundingClientRect().top > HEADER_OFFSET_PX + 4) break;
        current = target.id;
      }
      return current;
    };

    // No initial `setActive` here: `observe()` delivers a callback for every
    // target right away, so the first mark arrives through the same path as
    // every later one — and a setState in an effect BODY is a cascading
    // render the lint rightly rejects.
    const sync = () => {
      if (Date.now() < pinnedUntil.current) return;
      setActive(currentSection());
    };

    const observer = new IntersectionObserver(sync, {
      // The observer is only the trigger; the answer above is read from
      // geometry. The band's TOP edge is the header line, so every heading
      // crossing it — in either direction — wakes the callback, and the bottom
      // margin keeps headings still far down the page from firing it.
      rootMargin: `-${HEADER_OFFSET_PX}px 0px -55% 0px`
    });

    // The last crossing of a smooth scroll can land ON the line, one frame
    // after the observer's final callback — so the end of the scroll gets the
    // final word. `scrollend` is ignored by browsers that lack it, where the
    // next scroll corrects the mark instead.
    const settle = () => {
      pinnedUntil.current = 0;
      setActive(currentSection());
    };
    window.addEventListener("scrollend", settle);

    for (const target of targets) observer.observe(target);
    return () => {
      observer.disconnect();
      window.removeEventListener("scrollend", settle);
    };
  }, [ids]);

  return [active, markSection] as const;
}

/**
 * Sends the reader to a section without losing the URL.
 *
 * `scroll-behavior: smooth` is deliberately NOT set on the document: Next.js
 * scrolls the window itself on every route change, and a global rule turns
 * those into an animation the reader did not ask for. Scoped here, the
 * animation only happens when someone clicks a section.
 */
function jumpToSection(event: MouseEvent<HTMLAnchorElement>, id: string, onJump?: (id: string) => void) {
  const target = document.getElementById(id);
  // No such heading (a stale anchor): let the browser handle the href.
  if (target === null) return;

  // Marked here rather than left to the observer: the smooth scroll ends with
  // the heading sitting ON the line, and the crossing callback that would have
  // claimed it may already have been delivered a frame earlier.
  onJump?.(id);

  event.preventDefault();
  // Keeps the address bar honest, so the section survives a copied link or a
  // reload — the reason this is a real anchor and not an onClick in the first
  // place.
  window.history.pushState(null, "", `#${id}`);

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView?.({ behavior: reduced ? "auto" : "smooth", block: "start" });

  // A jump that moves the viewport but not the keyboard leaves a keyboard or
  // screen-reader user back where they started; headings are not focusable on
  // their own, so the target borrows a programmatic tab stop.
  target.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
}

/**
 * Section list for the published regulations.
 *
 * Real anchors with real `href`s — middle-click, "copy link address" and a
 * no-JavaScript render all keep working; the click handler only adds the
 * smooth scroll and the focus move on top of what the browser already does.
 */
export function RulesToc({
  entries,
  activeId,
  onJump,
  className
}: Readonly<{
  entries: TocEntry[];
  activeId?: string | null;
  onJump?: (id: string) => void;
  className?: string;
}>) {
  const t = useTranslations();

  return (
    <nav aria-label={t("tournamentDetail.rules.toc")} className={cn("text-body", className)}>
      <ol className="border-l border-border">
        {entries.map((entry, index) => {
          const isActive = entry.id === activeId;

          return (
            // Index in the key, not the id alone: two sections may share a
            // title, and React needs the pair to stay unique even when the
            // anchor does not (see `slugifyHeading`).
            <li key={`${entry.id}-${index}`}>
              <a
                href={`#${entry.id}`}
                onClick={(event) => jumpToSection(event, entry.id, onJump)}
                aria-current={isActive ? "true" : undefined}
                className={cn(
                  "block border-l-2 py-1 pr-2 transition-colors",
                  entry.level === 3 ? "pl-7 text-caption" : "pl-4",
                  isActive
                    ? "border-primary font-medium text-foreground"
                    : "border-transparent text-muted-foreground hover:border-primary/50 hover:text-foreground"
                )}
              >
                {entry.text}
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
