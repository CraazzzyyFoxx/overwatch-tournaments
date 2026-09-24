"use client";

import { useEffect, useRef, type KeyboardEvent } from "react";
import Link from "next/link";

import type { Tone } from "@/components/kit/tone";
import { TabBadge, TabDot, revealTab, tabsListVariants, tabsTriggerVariants } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

export interface LinkTabItem {
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

export interface LinkTabsProps {
  items: LinkTabItem[];
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
 * Routed tabs and sub-tabs: one real link per tab with `aria-current="page"`.
 * State-driven tabs with panels are `Tabs` from `components/ui/tabs.tsx`; both
 * draw from the same classes there, so a routed row and a local row look the
 * same everywhere.
 *
 * Deliberately NOT Radix `Tabs`: a routed tab is a link, not a `role=tab` with
 * a panel, and a nested sub-tab row would fight the outer row's roving
 * tabindex. Arrow-key movement is added by hand below so the keyboard
 * affordance survives.
 *
 * Narrow viewports scroll the row horizontally rather than wrapping it (F18),
 * and the active tab is scrolled into view so a deep link does not land on an
 * off-screen tab.
 */
export function LinkTabs({ items, activeKey, level = 1, ariaLabel }: Readonly<LinkTabsProps>) {
  const listRef = useRef<HTMLUListElement>(null);
  const activeRef = useRef<HTMLAnchorElement | null>(null);
  const visible = items.filter((item) => !item.hidden);

  useEffect(() => {
    if (listRef.current && activeRef.current) revealTab(listRef.current, activeRef.current);
  }, [activeKey]);

  const handleKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    const links = Array.from(
      listRef.current?.querySelectorAll<HTMLAnchorElement>("a[data-link-tab]") ?? []
    );
    const index = links.indexOf(document.activeElement as HTMLAnchorElement);
    if (index === -1) return;
    event.preventDefault();
    const delta = event.key === "ArrowRight" ? 1 : -1;
    links[(index + delta + links.length) % links.length]?.focus();
  };

  return (
    <nav aria-label={ariaLabel}>
      <ul
        ref={listRef}
        onKeyDown={handleKeyDown}
        className={cn(tabsListVariants({ variant: "underline" }), level === 2 && "shadow-none")}
      >
        {visible.map((item) => {
          const isActive = item.key === activeKey;
          return (
            <li key={item.key} className="shrink-0">
              <Link
                href={item.href}
                data-link-tab={item.key}
                ref={isActive ? activeRef : undefined}
                aria-current={isActive ? "page" : undefined}
                className={tabsTriggerVariants({ variant: "underline" })}
              >
                {item.dot ? <TabDot {...item.dot} /> : null}
                {item.label}
                {item.badge ? <TabBadge>{item.badge}</TabBadge> : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
