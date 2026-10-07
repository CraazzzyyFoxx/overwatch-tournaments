import { describe, expect, it } from "vitest";

import {
  adminNavItemSearchValue,
  adminNavigationGroups,
  getActiveAdminNavHref,
  getMatchingAdminRoute,
  getVisibleAdminNavigationGroups,
} from "@/components/admin/admin-navigation";

const allItems = adminNavigationGroups.flatMap((group) => group.items);

describe("admin navigation structure", () => {
  it("is four groups: unlabelled, DATA, WORKSPACE, PLATFORM", () => {
    expect(adminNavigationGroups.map((group) => group.title)).toEqual([
      "",
      "DATA",
      "WORKSPACE",
      "PLATFORM",
    ]);
  });

  it("is sixteen entries, not twenty-four", () => {
    expect(allItems).toHaveLength(16);
    expect(allItems.map((item) => item.href)).toEqual([
      "/admin",
      "/admin/tournaments",
      "/admin/people",
      "/admin/ranks",
      "/admin/teams",
      "/admin/matches",
      "/admin/achievements",
      "/admin/settings/general",
      "/admin/members",
      "/admin/content/heroes",
      "/admin/collectors/rank",
      "/admin/access",
      "/admin/workspaces",
      "/admin/announcements",
      "/admin/notifications",
      "/admin/audit",
    ]);
  });

  it("registers each destination exactly once", () => {
    const hrefs = allItems.map((item) => item.href);
    expect(hrefs).toEqual([...new Set(hrefs)]);
  });

  it("drops a group entirely once none of its entries is reachable", () => {
    // A reader holding nothing but `match.read`: Dashboard (its entry set
    // includes match.read) and Matches survive, so WORKSPACE and PLATFORM
    // must disappear with their contents rather than leaving a labelled
    // empty group.
    const groups = getVisibleAdminNavigationGroups((item) =>
      (item.permissions ?? []).includes("match.read"),
    );

    expect(groups.map((group) => group.title)).toEqual(["", "DATA"]);
    expect(groups.flatMap((group) => group.items.map((item) => item.title))).toEqual([
      "Dashboard",
      "Matches",
    ]);
  });

  it("shows the workspace-scoped entries to a workspace admin", () => {
    const groups = getVisibleAdminNavigationGroups((item) => item.workspaceAdminVisible === true);
    const hrefs = groups.flatMap((group) => group.items.map((item) => item.href));

    expect(hrefs).toContain("/admin/settings/general");
    expect(hrefs).toContain("/admin/members");
    expect(hrefs).toContain("/admin/workspaces");
  });

  it("keeps game content behind superuser", () => {
    const groups = getVisibleAdminNavigationGroups((item) => item.superuserOnly !== true);
    const hrefs = groups.flatMap((group) => group.items.map((item) => item.href));

    expect(hrefs).not.toContain("/admin/content/heroes");
    expect(getMatchingAdminRoute("/admin/content/heroes")?.superuserOnly).toBe(true);
  });

  it("gives Collectors one OR-list instead of three entries", () => {
    // `canAccessAdminRoute` reads a permission list as OR, so a holder of any
    // one collector permission gets the entry — and the streams-only global
    // gate stays on the route, not on the menu.
    const collectors = allItems.find((item) => item.title === "Collectors");

    expect(collectors?.permissions).toEqual(["rank.read", "subscription.read", "stream.read"]);
    expect(collectors?.globalOnly).toBeUndefined();
    expect(getMatchingAdminRoute("/admin/collectors/streams")?.globalOnly).toBe(true);
    expect(getMatchingAdminRoute("/admin/collectors/rank")?.globalOnly).toBeUndefined();
  });
});

describe("active-entry matching", () => {
  it("lights the entry that owns the deepest matching prefix", () => {
    const items = allItems;

    expect(getActiveAdminNavHref("/admin", items)).toBe("/admin");
    expect(getActiveAdminNavHref("/admin/tournaments/14/bracket", items)).toBe("/admin/tournaments");
    expect(getActiveAdminNavHref("/admin/teams/9", items)).toBe("/admin/teams");
  });

  it("keeps Settings active across every section, not just its landing one", () => {
    // The entry points at `/admin/settings/general`; without `activePrefix`
    // the sidebar would go dark on `/admin/settings/divisions`.
    expect(getActiveAdminNavHref("/admin/settings/divisions", allItems)).toBe(
      "/admin/settings/general",
    );
    expect(getActiveAdminNavHref("/admin/content/unresolved", allItems)).toBe(
      "/admin/content/heroes",
    );
    expect(getActiveAdminNavHref("/admin/access/roles", allItems)).toBe("/admin/access");
  });

  it("does not light Dashboard on every admin route", () => {
    expect(getActiveAdminNavHref("/admin/audit", allItems)).toBe("/admin/audit");
  });
});

describe("route gates", () => {
  it.each([
    ["/admin/people", ["user.read"]],
    ["/admin/people/42", ["user.read"]],
    ["/admin/ranks", ["team.update"]],
    ["/admin/teams", ["team.read"]],
    ["/admin/matches", ["match.read"]],
    ["/admin/matches/42", ["match.read"]],
    ["/admin/achievements", ["achievement.read"]],
    ["/admin/audit", ["audit.read"]],
    ["/admin/tournaments/14/settings/danger", ["tournament.read"]],
    ["/admin/settings/statuses", ["team.read"]],
    ["/admin/settings/sub-roles", ["player.read"]],
    ["/admin/collectors/rank", ["rank.read"]],
    ["/admin/collectors/subscriptions", ["subscription.read"]],
    ["/admin/collectors/streams", ["stream.read"]],
  ])("gates %s on %j", (path, permissions) => {
    expect(getMatchingAdminRoute(path)?.permissions).toEqual(permissions);
  });

  it("resolves a section to its own prefix, never a neighbour's", () => {
    expect(getMatchingAdminRoute("/admin/settings/statuses")?.prefix).toBe(
      "/admin/settings/statuses",
    );
    expect(getMatchingAdminRoute("/admin/settings/branding")?.prefix).toBe("/admin/settings");
    expect(getMatchingAdminRoute("/admin/members")?.prefix).toBe("/admin/members");
    // `/admin/matches` must not swallow the collectors' own prefixes, and
    // `/admin/settings/sub-roles` must not fall back to `/admin/settings`.
    expect(getMatchingAdminRoute("/admin/settings/sub-roles")?.prefix).toBe(
      "/admin/settings/sub-roles",
    );
    expect(getMatchingAdminRoute("/admin/collectors/streams")?.prefix).toBe(
      "/admin/collectors/streams",
    );
  });

  it("carries no row for a route the redesign retired", () => {
    // The transitional rows are gone now that P5 landed. A prefix that
    // outlives its screen is not harmless: it is a gate nobody can reach,
    // and the next reader trusts it.
    for (const retired of [
      "/admin/users",
      "/admin/players",
      "/admin/balancer",
      "/admin/sub-roles",
      "/admin/divisions",
      "/admin/encounters",
      "/admin/match-reports",
      "/admin/standings",
      "/admin/rank",
      "/admin/subscriptions",
      "/admin/streams",
      "/admin/heroes",
      "/admin/maps",
      "/admin/gamemodes",
      "/admin/aliases",
      "/admin/access/users",
      "/admin/workspaces/members"
    ]) {
      // They all fall through to the catch-all, which is correct: every one of
      // them 308s away before a page is ever rendered.
      expect(getMatchingAdminRoute(retired)?.prefix, retired).not.toBe(retired);
    }
  });

  it("keeps a workspace grant enough for the workspace-scoped surfaces", () => {
    expect(getMatchingAdminRoute("/admin/settings/branding")?.workspaceAdminVisible).toBe(true);
    expect(getMatchingAdminRoute("/admin/members")?.workspaceAdminVisible).toBe(true);
    expect(getMatchingAdminRoute("/admin/audit")?.workspaceAdminVisible).toBe(true);
    expect(getMatchingAdminRoute("/admin/access/api-keys")?.workspaceAdminVisible).toBe(true);
    expect(getMatchingAdminRoute("/admin/people")?.globalOnly).toBeUndefined();
  });

  it("has a gate for every route in the IA route map", () => {
    // A path with no row falls through to `/admin`, whose gate is the broad
    // entry set — which is how a superuser-only screen leaks.
    const routes = [
      "/admin",
      "/admin/tournaments",
      "/admin/tournaments/new",
      "/admin/tournaments/14/overview",
      "/admin/tournaments/14/registration/entries",
      "/admin/tournaments/14/teams/roster",
      "/admin/tournaments/14/teams/draft",
      "/admin/tournaments/14/bracket",
      "/admin/tournaments/14/matches/encounters",
      "/admin/tournaments/14/settings/general",
      "/admin/people",
      "/admin/people/42",
      "/admin/ranks",
      "/admin/teams",
      "/admin/teams/9",
      "/admin/matches",
      "/admin/achievements",
      "/admin/achievements/3",
      "/admin/settings/general",
      "/admin/settings/divisions",
      "/admin/settings/divisions/v/4",
      "/admin/settings/divisions/import",
      "/admin/settings/statuses",
      "/admin/settings/sub-roles",
      "/admin/settings/subscriptions",
      "/admin/members",
      "/admin/content/heroes",
      "/admin/content/unresolved",
      "/admin/collectors/rank",
      "/admin/collectors/subscriptions",
      "/admin/collectors/streams",
      "/admin/access",
      "/admin/access/accounts",
      "/admin/access/roles",
      "/admin/access/permissions",
      "/admin/access/api-keys",
      "/admin/access/oauth",
      "/admin/access/sessions",
      "/admin/workspaces",
      "/admin/workspaces/8/general",
      "/admin/announcements",
      "/admin/audit",
    ];

    for (const route of routes) {
      const match = getMatchingAdminRoute(route);
      expect(match, route).toBeDefined();
      if (route !== "/admin") {
        expect(match?.prefix, route).not.toBe("/admin");
      }
    }
  });
});

describe("command palette", () => {
  it("keeps aliases unambiguous — one alias never hits two entries", () => {
    const aliases = allItems.flatMap((item) => item.aliases ?? []);

    expect(aliases).toEqual([...new Set(aliases)]);
  });

  it("re-homes the aliases of every page the new IA absorbed", () => {
    const byAlias = (alias: string) =>
      allItems.filter((item) => item.aliases?.includes(alias)).map((item) => item.title);

    expect(byAlias("identities")).toEqual(["People"]);
    expect(byAlias("battletag")).toEqual(["People"]);
    expect(byAlias("players")).toEqual(["People"]);
    expect(byAlias("encounters")).toEqual(["Matches"]);
    expect(byAlias("subroles")).toEqual(["Settings"]);
    expect(byAlias("divisions")).toEqual(["Settings"]);
    expect(byAlias("balancer")).toEqual(["Settings"]);
    expect(byAlias("poller")).toEqual(["Collectors"]);
    expect(byAlias("boosty")).toEqual(["Collectors"]);
    expect(byAlias("api keys")).toEqual(["Access"]);
    expect(byAlias("alias queue")).toEqual(["Game content"]);
    expect(byAlias("who changed this")).toEqual(["Audit log"]);
  });

  it("offers a view for each collapsed page so it stays findable", () => {
    const matches = allItems.find((item) => item.title === "Matches");

    expect(matches?.views?.map((view) => view.key)).toEqual([
      "encounters",
      "standings",
      "reports",
      "parsed",
      "logs",
    ]);
    expect(matches?.views?.find((view) => view.key === "standings")?.href).toBe(
      "/admin/matches?view=standings",
    );
  });

  it("gives every view a unique destination", () => {
    const hrefs = allItems.flatMap((item) => (item.views ?? []).map((view) => view.href));

    expect(hrefs).toEqual([...new Set(hrefs)]);
  });

  it("includes aliases in the search value", () => {
    const people = allItems.find((item) => item.href === "/admin/people");

    expect(people).toBeDefined();
    expect(adminNavItemSearchValue(people!)).toContain("battletag");
    expect(adminNavItemSearchValue(people!)).toContain(people!.title);
  });
});
