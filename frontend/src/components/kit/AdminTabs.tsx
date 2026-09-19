"use client";

import { useEffect, useRef, type KeyboardEvent } from "react";
import Link from "next/link";

import { TONE_TEXT, type Tone } from "@/components/kit/tone";
import { cn } from "@/lib/utils";

export interface AdminTabItem {
  key: string;
  label: string;
  href: string;
  /** Queue size (disputed reports, pending logs). A count, never an annotation. */
  badge?: number;
  /**
   * Health marker before the label (a collector's poller state, F14).
   *
   * `label` is required and rendered `sr-only`: the design book bans
   * colour-only encoding, so the dot always carries the word too.
   */
  dot?: { tone: Tone; label: string };
  hidden?: boolean;
}

export interface AdminTabsProps {
  items: AdminTabItem[];
  activeKey: string;
  /**
   * `1` is a screen's own tab row; `2` is a sub-tab row nested under it. Same
   * tab size at both levels — the hierarchy is carried by position and by the
   * hairline under the first row, not by shrinking the second.
   */
  level?: 1 | 2;
  ariaLabel: string;
}

/**
 * The one tab implementation for the whole admin panel.
 *
 * Deliberately NOT Radix `Tabs`: its roving tabindex owns arrow keys for the
 * whole tablist, so a second (sub-tab) row nested under the first fights the
 * outer one for focus — the reason `tournaments/[id]/matches/layout.tsx` had a
 * hand-rolled `<nav>`. These are real links with `aria-current="page"`, which
 * is also what a routed tab actually is; arrow-key movement is added by hand
 * below so the keyboard affordance survives.
 *
 * Narrow viewports scroll the row horizontally rather than wrapping it (F18),
 * and the active tab is scrolled into view on mount so a deep link does not
 * land on an off-screen tab.
 */
export function AdminTabs({ items, activeKey, level = 1, ariaLabel }: Readonly<AdminTabsProps>) {
  const listRef = useRef<HTMLUListElement>(null);
  const activeRef = useRef<HTMLAnchorElement | null>(null);
  const visible = items.filter((item) => !item.hidden);

  useEffect(() => {
    // Guarded: happy-dom and older Safari do not implement the options form.
    activeRef.current?.scrollIntoView?.({ inline: "nearest", block: "nearest" });
  }, [activeKey]);

  const handleKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    const links = Array.from(
      listRef.current?.querySelectorAll<HTMLAnchorElement>("a[data-admin-tab]") ?? []
    );
    const index = links.indexOf(document.activeElement as HTMLAnchorElement);
    if (index === -1) return;
    event.preventDefault();
    const delta = event.key === "ArrowRight" ? 1 : -1;
    links[(index + delta + links.length) % links.length]?.focus();
  };

  return (
    <nav
      aria-label={ariaLabel}
      className={cn("border-b border-border", level === 2 && "border-b-0")}
    >
      <ul
        ref={listRef}
        onKeyDown={handleKeyDown}
        className="-mb-px flex w-full items-center gap-1 overflow-x-auto whitespace-nowrap"
      >
        {visible.map((item) => {
          const isActive = item.key === activeKey;
          return (
            <li key={item.key} className="shrink-0">
              <Link
                href={item.href}
                data-admin-tab={item.key}
                ref={isActive ? activeRef : undefined}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "inline-flex h-9 items-center gap-1.5 border-b-2 px-3 text-sm transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background",
                  isActive
                    ? "border-primary text-foreground font-medium"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                {item.dot ? (
                  <>
                    <span
                      aria-hidden
                      className={cn(
                        "size-1.5 shrink-0 rounded-full bg-current",
                        TONE_TEXT[item.dot.tone]
                      )}
                    />
                    <span className="sr-only">{item.dot.label}</span>
                  </>
                ) : null}
                {item.label}
                {item.badge ? (
                  <span
                    className={cn(
                      "rounded-full px-1.5 py-0.5 text-xs tabular-nums",
                      isActive
                        ? "bg-primary/15 text-primary"
                        : "bg-muted/40 text-muted-foreground"
                    )}
                  >
                    {item.badge}
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
