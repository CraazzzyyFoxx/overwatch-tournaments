"use client";

import React from "react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger
} from "@/components/ui/accordion";
import {
  NavigationMenu,
  NavigationMenuContent,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  NavigationMenuTrigger
} from "@/components/ui/navigation-menu";
import { cn } from "@/lib/utils";
import { isNavGroupActive } from "./site-nav-groups";
import { useVisibleNavGroups } from "./useVisibleNavGroups";

// Redesign nav-link look (flat, teal-active) — overrides the shared
// navigationMenuTriggerStyle() via twMerge conflict resolution.
const navTriggerClass =
  "h-8 rounded-lg bg-transparent px-3 text-caption font-medium text-[color:var(--aqt-fg-muted)] " +
  "hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] " +
  "focus:bg-[color:var(--aqt-overlay-3)] focus:text-[color:var(--aqt-fg)] " +
  "data-[state=open]:bg-[color:var(--aqt-overlay-3)] data-[state=open]:text-[color:var(--aqt-fg)]";

const navTriggerActiveClass =
  "bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)] text-[color:var(--aqt-teal)] " +
  "hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_16%,transparent)] hover:text-[color:var(--aqt-teal)] " +
  "focus:bg-[color:color-mix(in_srgb,var(--aqt-teal)_16%,transparent)] focus:text-[color:var(--aqt-teal)] " +
  "data-[state=open]:bg-[color:color-mix(in_srgb,var(--aqt-teal)_16%,transparent)] data-[state=open]:text-[color:var(--aqt-teal)]";

const ListItem = React.forwardRef<React.ElementRef<"a">, React.ComponentPropsWithoutRef<"a">>(
  ({ className, title, children, ...props }, ref) => {
    return (
      <li>
        <NavigationMenuLink asChild>
          <a
            ref={ref}
            className={cn(
              "block select-none space-y-1 rounded-md p-3 leading-none no-underline transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              className
            )}
            {...props}
          >
            <div className="text-sm font-medium leading-none">{title}</div>
            <p className="line-clamp-2 text-sm leading-snug text-muted-foreground">{children}</p>
          </a>
        </NavigationMenuLink>
      </li>
    );
  }
);
ListItem.displayName = "ListItem";

interface SiteNavProps {
  /** `desktop` renders the click-to-open NavigationMenu; `mobile` the sheet Accordion. */
  variant: "desktop" | "mobile";
  className?: string;
}

/**
 * The public site navigation. Both surfaces render the same tree from
 * `useVisibleNavGroups()` and the same `nav.*` message lookups — the header
 * previously carried two hand-maintained copies, so any nav change had to be
 * made twice.
 *
 * A group holding a single item renders as a direct link, not a disclosure:
 * a dropdown that opens onto one row makes the reader pay an extra click and a
 * guess for nothing. The link is labelled with the ITEM's title, because that
 * is where it actually goes — "Organization" promises a section, "Admin" names
 * the destination. This is a rule about arity, not about a specific group, so
 * adding a second item turns the disclosure back on by itself.
 */
export function SiteNav({ variant, className }: Readonly<SiteNavProps>) {
  const t = useTranslations();
  const pathname = usePathname() ?? "";
  const groups = useVisibleNavGroups();

  const titleOf = (key: string) => t(`nav.items.${key}.title` as Parameters<typeof t>[0]);

  if (variant === "mobile") {
    return (
      <Accordion type="single" collapsible className={cn("w-full", className)}>
        {groups.map((group) => {
          const [only] = group.items;
          if (group.items.length === 1) {
            return (
              <HoverPrefetchLink
                key={group.key}
                href={only.href}
                aria-current={isNavGroupActive(group.items, pathname) ? "page" : undefined}
                className={cn(
                  "flex items-center border-b py-4 text-base font-medium transition-colors hover:underline",
                  isNavGroupActive(group.items, pathname)
                    ? "text-[color:var(--aqt-teal)]"
                    : "text-foreground"
                )}
              >
                {titleOf(only.key)}
              </HoverPrefetchLink>
            );
          }

          return (
            <AccordionItem key={group.key} value={group.key}>
              <AccordionTrigger className="text-base hover:text-foreground">
                {t(`nav.groups.${group.key}`)}
              </AccordionTrigger>
              <AccordionContent>
                <div className="grid gap-4 pl-4">
                  {group.items.map((item) => (
                    <HoverPrefetchLink
                      key={item.key}
                      href={item.href}
                      className="text-sm text-muted-foreground hover:text-foreground"
                    >
                      {titleOf(item.key)}
                    </HoverPrefetchLink>
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          );
        })}
      </Accordion>
    );
  }

  return (
    <NavigationMenu className={cn("hidden lg:flex", className)}>
      {/* One list, not one per group: N single-item <ul>s told assistive
          technology the header held N separate navigations. */}
      <NavigationMenuList>
        {groups.map((group) => {
          const isActive = isNavGroupActive(group.items, pathname);
          const [only] = group.items;

          if (group.items.length === 1) {
            return (
              <NavigationMenuItem key={group.key}>
                <NavigationMenuLink asChild>
                  <HoverPrefetchLink
                    href={only.href}
                    aria-current={isActive ? "page" : undefined}
                    className={cn(
                      "inline-flex w-max items-center justify-center transition-colors focus:outline-none",
                      navTriggerClass,
                      isActive && navTriggerActiveClass
                    )}
                  >
                    {titleOf(only.key)}
                  </HoverPrefetchLink>
                </NavigationMenuLink>
              </NavigationMenuItem>
            );
          }

          return (
            <NavigationMenuItem key={group.key}>
              <NavigationMenuTrigger
                className={cn(navTriggerClass, isActive && navTriggerActiveClass)}
              >
                {t(`nav.groups.${group.key}`)}
              </NavigationMenuTrigger>
              <NavigationMenuContent>
                <ul className="grid w-100 gap-3 p-4 md:w-125 md:grid-cols-2 lg:w-150">
                  {group.items.map((item) => (
                    <ListItem key={item.key} title={titleOf(item.key)} href={item.href}>
                      {t(`nav.items.${item.key}.desc` as Parameters<typeof t>[0])}
                    </ListItem>
                  ))}
                </ul>
              </NavigationMenuContent>
            </NavigationMenuItem>
          );
        })}
      </NavigationMenuList>
    </NavigationMenu>
  );
}

export default SiteNav;
