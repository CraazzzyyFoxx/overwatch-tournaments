"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useLayoutEffect, useRef } from "react";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { SettingsOutlineList } from "@/components/kit/SettingsOutline";
import { playEnter, type Edge } from "@/components/kit/SettingsContinuation";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { cn } from "@/lib/utils";

interface SectionNavItem {
  key: string;
  label: string;
  href: string;
  /** `danger` marks the destructive section (a Danger zone). */
  tone?: "danger";
  hidden?: boolean;
}

export interface SectionNavGroup {
  label?: string;
  items: SectionNavItem[];
}

export interface SectionNavProps {
  groups: SectionNavGroup[];
  activeKey: string;
}

/**
 * The page a rail pick just opened, and where it enters from: below for an
 * item under the current one, above for one over it — the way a scroll
 * between them would go. Consumed by `useSectionNavEntrance` on the next
 * route change, whatever that change turns out to be.
 */
let picked: { href: string; edge: Edge } | null = null;

// A module-level writer: the rail's handlers record a pick, render never does.
function recordPick(href: string, edge: Edge) {
  picked = { href, edge };
}

/**
 * Ref for the content column beside the rail: a rail pick plays the scroll
 * chain's entrance on it, so picking a section moves like scrolling to it.
 */
export function useSectionNavEntrance<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const pathname = usePathname();
  const reduced = usePrefersReducedMotion();
  // Before paint, so the new page never shows a frame before its first keyframe.
  useLayoutEffect(() => {
    const pick = picked;
    picked = null;
    if (pick?.href === pathname && !reduced) playEnter(ref.current, pick.edge);
  }, [pathname, reduced]);
  return ref;
}

/**
 * The section rail for every T5 settings screen.
 *
 * A settings hub has too many sections for a tab row (tournament settings has
 * eleven), so they become a vertical list of links. Below `lg` the admin
 * sidebar and a 200px rail would leave the form a sliver, so the same list
 * becomes a `Select` — still one URL per section, so a link to "Danger zone"
 * is shareable.
 */
export function SectionNav({ groups, activeKey }: Readonly<SectionNavProps>) {
  const t = useTranslations("kit.actions");
  const router = useRouter();
  const visibleGroups = groups
    .map((group) => ({ ...group, items: group.items.filter((item) => !item.hidden) }))
    .filter((group) => group.items.length > 0);
  const allItems = visibleGroups.flatMap((group) => group.items);
  const active = allItems.find((item) => item.key === activeKey);
  const activeIndex = active ? allItems.indexOf(active) : -1;
  const pick = (item: SectionNavItem) =>
    recordPick(item.href, allItems.indexOf(item) < activeIndex ? "bottom" : "top");

  // One section is not a choice: no rail, no select.
  if (allItems.length < 2) return null;

  return (
    <>
      <div className="lg:hidden">
        <Select
          value={active?.key ?? ""}
          onValueChange={(key) => {
            const target = allItems.find((item) => item.key === key);
            if (!target) return;
            pick(target);
            router.push(target.href);
          }}
        >
          <SelectTrigger aria-label={t("settingsSection")}>
            <SelectValue placeholder={t("selectSection")} />
          </SelectTrigger>
          <SelectContent>
            {visibleGroups.map((group) => (
              <SelectGroup key={group.label ?? "ungrouped"}>
                {group.label ? <SelectLabel>{group.label}</SelectLabel> : null}
                {group.items.map((item) => (
                  <SelectItem key={item.key} value={item.key}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Sticky below the admin top bar (`h-12`), so a long form never scrolls
          the way out of reach. */}
      <nav
        aria-label={t("settingsSections")}
        className="hidden w-[200px] shrink-0 lg:sticky lg:top-16 lg:block lg:max-h-[calc(100dvh-5rem)] lg:self-start lg:overflow-y-auto"
      >
        {visibleGroups.map((group) => (
          <div key={group.label ?? "ungrouped"} className="mb-4 last:mb-0">
            {group.label ? <p className={cn(eyebrowClass("muted"), "mb-1.5 px-2")}>{group.label}</p> : null}
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const isActive = item.key === activeKey;
                return (
                  <li key={item.key}>
                    <Link
                      href={item.href}
                      aria-current={isActive ? "page" : undefined}
                      onClick={(event) => {
                        // A new-tab click leaves this page where it is.
                        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
                          return;
                        }
                        pick(item);
                      }}
                      className={cn(
                        "block rounded-md px-2 py-1.5 text-sm transition-colors",
                        "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
                        isActive
                          ? "bg-accent/40 font-medium text-foreground"
                          : "text-muted-foreground hover:text-foreground",
                        item.tone === "danger" && !isActive && "text-danger/80 hover:text-danger"
                      )}
                    >
                      {item.label}
                    </Link>
                    {/* The open page's groups, when a `SettingsOutlineProvider`
                        wraps this rail and the page has enough of them. */}
                    {isActive ? <SettingsOutlineList /> : null}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </>
  );
}
