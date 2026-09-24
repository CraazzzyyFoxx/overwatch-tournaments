"use client";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { LinkTabs } from "@/components/kit/LinkTabs";
import { cn } from "@/lib/utils";
import { NAV_GROUPS, currentNavHref, sectionPageGroup } from "./site-nav-groups";
import { useCanAccessAdminEntry } from "./useCanAccessAdminEntry";

const sectionLinkClass =
  "inline-flex h-8 items-center whitespace-nowrap rounded-lg px-3 text-caption font-medium " +
  "text-[color:var(--aqt-fg-muted)] transition-colors " +
  "hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

const sectionLinkActiveClass =
  "bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)] text-[color:var(--aqt-teal)] " +
  "hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_16%,transparent)] hover:text-[color:var(--aqt-teal)]";

const sheetLinkClass =
  "flex items-center py-2 text-base font-medium text-foreground transition-colors hover:text-[color:var(--aqt-teal)]";

interface SiteNavProps {
  /** `desktop` is the header's section links; `mobile` the sheet's full list. */
  variant: "desktop" | "mobile";
  className?: string;
}

/**
 * The public site navigation, from the one `NAV_GROUPS` tree and the same
 * `nav.*` lookups on both surfaces.
 *
 * Desktop names the sections only, each linking to its first page; the pages
 * of the section you are in are `SectionTabs` under the header. No
 * disclosures: a dropdown opening onto two to four rows cost a click and a
 * guess on every visit. The mobile sheet has room for the whole tree, so it
 * lists every page, groups separated by a rule.
 */
export function SiteNav({ variant, className }: Readonly<SiteNavProps>) {
  const t = useTranslations();
  const pathname = usePathname() ?? "";
  const current = currentNavHref(pathname);

  // `page` only on the page itself; anywhere deeper the link marks the current
  // location, not the current page.
  const ariaCurrentOf = (href: string, active: boolean) =>
    active ? (href === pathname ? "page" : "true") : undefined;

  if (variant === "mobile") {
    return (
      <div className={cn("grid", className)}>
        {NAV_GROUPS.map((group) => (
          <ul
            key={group.key}
            aria-label={t(`nav.groups.${group.key}`)}
            className="grid border-b py-2 first:pt-0"
          >
            {group.items.map((item) => (
              <li key={item.key}>
                <HoverPrefetchLink
                  href={item.href}
                  aria-current={ariaCurrentOf(item.href, item.href === current)}
                  className={cn(
                    sheetLinkClass,
                    item.href === current && "text-[color:var(--aqt-teal)]"
                  )}
                >
                  {t(`nav.items.${item.key}.title` as Parameters<typeof t>[0])}
                </HoverPrefetchLink>
              </li>
            ))}
          </ul>
        ))}
        <SiteAdminLink variant="mobile" />
      </div>
    );
  }

  return (
    <nav aria-label={t("nav.label")} className={cn("hidden lg:block", className)}>
      <ul className="flex items-center gap-0.5">
        {NAV_GROUPS.map((group) => {
          const [landing] = group.items;
          const isActive = group.items.some((item) => item.href === current);
          return (
            <li key={group.key}>
              <HoverPrefetchLink
                href={landing.href}
                aria-current={ariaCurrentOf(landing.href, isActive)}
                className={cn(sectionLinkClass, isActive && sectionLinkActiveClass)}
              >
                {t(`nav.groups.${group.key}`)}
              </HoverPrefetchLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/**
 * The pages of the current section as a tab row under the header.
 *
 * Only on a page of the tree itself. A detail page (a tournament, a player)
 * already carries its own tab row, and stacking a second one above it reads as
 * two competing navigations; there the header's section link alone says where
 * you are.
 *
 * The row and the header read as one block: the header drops its bottom rule
 * while this row shows (`Header`), and this row draws the header's rule —
 * full-width and in the header's tint — under the tabs instead of the tab
 * list's own inset baseline.
 */
export function SectionTabs() {
  const t = useTranslations();
  const pathname = usePathname() ?? "";
  const group = sectionPageGroup(pathname);
  if (!group) return null;

  return (
    // The inset is the header's gutter minus a tab's padding, so the first
    // label lines up with the logo above it.
    <div className="px-1 shadow-[inset_0_-1px_0_hsl(var(--border)/0.7)] md:px-3">
      <LinkTabs
        level={2}
        ariaLabel={t(`nav.groups.${group.key}`)}
        activeKey={pathname}
        items={group.items.map((item) => ({
          key: item.href,
          label: t(`nav.items.${item.key}.title` as Parameters<typeof t>[0]),
          href: item.href
        }))}
      />
    </div>
  );
}

/**
 * The admin entry, for viewers who have one. It is a personal tool rather than
 * a section of the site, so on desktop it sits with the account controls; in
 * the mobile sheet it closes the list.
 */
export function SiteAdminLink({ variant }: Readonly<{ variant: "header" | "mobile" }>) {
  const t = useTranslations();
  const canAccess = useCanAccessAdminEntry();
  if (!canAccess) return null;

  return (
    <HoverPrefetchLink
      href="/admin"
      className={
        variant === "header"
          ? cn(sectionLinkClass, "hidden lg:inline-flex")
          : cn(sheetLinkClass, "pt-4")
      }
    >
      {t("nav.items.admin.title")}
    </HoverPrefetchLink>
  );
}

export default SiteNav;
