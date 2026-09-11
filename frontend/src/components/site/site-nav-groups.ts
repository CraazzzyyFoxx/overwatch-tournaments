/**
 * The public site's navigation tree — the single definition.
 *
 * It is data-driven by stable keys; the visible text (group labels, item titles
 * and descriptions) is resolved from the `nav.*` message namespace at render
 * time, because module scope has no `t()`. `href` drives active-state matching,
 * `key` drives translation lookup.
 */

export type NavGroupKey = "tournaments" | "users" | "matches" | "organization";

export interface NavItem {
  key: string;
  href: string;
  requiresAdminAccess?: boolean;
}

export interface NavGroup {
  key: NavGroupKey;
  items: readonly NavItem[];
}

// Annotated rather than `as const satisfies`: `as const` narrows each item to a
// literal shape, so an item without `requiresAdminAccess` loses the property
// and consumers cannot read it off the union.
export const NAV_GROUPS: readonly NavGroup[] = [
  {
    key: "tournaments",
    items: [
      { key: "tournaments", href: "/tournaments" },
      { key: "teams", href: "/teams" },
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
    key: "matches",
    items: [
      { key: "encounters", href: "/encounters" },
      { key: "matches", href: "/matches" },
      // Ad-hoc pre-game rooms (docs/plans/2026-08-12-scrim-rooms.md). Sits with
      // encounters/matches rather than under tournaments: a scrim belongs to no
      // tournament, and this is where a captain already looks for "a series".
      { key: "scrims", href: "/scrims" },
      // Mix lobbies balanced from a workspace roster. Viewing one is public
      // (signed out included) -- only hosting (create/update/delete) needs the
      // `custom_game` grant, gated inside the mix pages/RPCs themselves, so
      // the entry carries no access flag here.
      { key: "mixes", href: "/balancer/mix" }
    ]
  },
  {
    key: "organization",
    items: [{ key: "admin", href: "/admin", requiresAdminAccess: true }]
  }
];

export function isNavGroupActive(items: readonly { href: string }[], pathname: string): boolean {
  return items.some((item) => {
    if (item.href === "/") return pathname === "/";
    return pathname === item.href || pathname.startsWith(`${item.href}/`);
  });
}
