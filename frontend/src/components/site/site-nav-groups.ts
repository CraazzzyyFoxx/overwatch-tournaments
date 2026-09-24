/**
 * The public site's navigation tree — the single definition.
 *
 * It is data-driven by stable keys; the visible text (group labels and item
 * titles) is resolved from the `nav.*` message namespace at render time,
 * because module scope has no `t()`. `href` drives current-page matching,
 * `key` drives translation lookup.
 *
 * Every item is public. The admin entry is permission-gated and lives beside
 * the account controls instead (`useCanAccessAdminEntry`), so nothing in this
 * tree needs filtering per viewer.
 */

export type NavGroupKey = "tournaments" | "users" | "play";

export interface NavItem {
  key: string;
  href: string;
}

export interface NavGroup {
  key: NavGroupKey;
  items: readonly NavItem[];
}

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    key: "tournaments",
    items: [
      { key: "tournaments", href: "/tournaments" },
      { key: "encounters", href: "/encounters" },
      { key: "analytics", href: "/tournaments/analytics" }
    ]
  },
  {
    key: "users",
    items: [
      { key: "users", href: "/users" },
      { key: "compare", href: "/users/compare" },
      { key: "heroesLeaderboard", href: "/users/heroes-compare" },
      { key: "achievements", href: "/achievements" }
    ]
  },
  {
    // What a player joins or hosts rather than browses. Scrim rooms
    // (docs/plans/2026-08-12-scrim-rooms.md) belong to no tournament; viewing a
    // mix is public (signed out included) and only hosting needs the
    // `custom_game` grant, gated inside the mix pages/RPCs themselves.
    key: "play",
    items: [
      { key: "scrims", href: "/scrims" },
      { key: "mixes", href: "/balancer/mix" }
    ]
  }
];

/**
 * The href of the item the reader is on: the longest item href that is the
 * path itself or a parent of it. Longest, because `/tournaments/analytics`
 * sits under `/tournaments` and `/users/compare` under `/users` — a plain
 * prefix test would mark both as current. A detail page (`/tournaments/x`)
 * resolves to its list page.
 */
export function currentNavHref(pathname: string): string | undefined {
  let current: string | undefined;
  for (const group of NAV_GROUPS) {
    for (const { href } of group.items) {
      const within = pathname === href || pathname.startsWith(`${href}/`);
      if (within && href.length > (current?.length ?? 0)) current = href;
    }
  }
  return current;
}

/**
 * The group whose page this exactly is, or undefined — on a detail page too.
 * It decides whether the section's tab row shows, so the header asks the same
 * question to know that row will draw its bottom rule.
 */
export function sectionPageGroup(pathname: string): NavGroup | undefined {
  return NAV_GROUPS.find((group) => group.items.some((item) => item.href === pathname));
}
