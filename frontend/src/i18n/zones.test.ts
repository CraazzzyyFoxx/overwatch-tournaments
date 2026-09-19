import { describe, expect, it } from "bun:test";

import en from "./messages/en.json";
import ZONE_NAMESPACES from "./zone-namespaces.json";
import { pickMessages, ZONES, zoneFromPathname, type Zone } from "./zones";

/**
 * The bundle *contents* are generated and drift-checked by
 * `scripts/check-zone-boundaries.mjs` (rule Z4) — it walks the import graph,
 * which a unit test cannot. What is tested here is the runtime half: the
 * pathname→zone mapping, that the picker actually narrows, and the invariant
 * that makes narrowing safe at all (root chrome present in every bundle).
 */

describe("zoneFromPathname", () => {
  it("maps route prefixes to their zone and defaults the rest to web", () => {
    const cases: ReadonlyArray<readonly [string, Zone]> = [
      ["/admin", "admin"],
      ["/admin/tournaments/12/bracket", "admin"],
      ["/balancer", "tools"],
      ["/balancer/mix/4", "tools"],
      ["/draft/9", "tools"],
      ["/", "web"],
      ["/tournaments/owal-2026/bracket", "web"],
      ["/users/anak", "web"],
      ["/_not-found", "web"],
    ];
    for (const [pathname, zone] of cases) {
      expect(zoneFromPathname(pathname)).toBe(zone);
    }
  });

  it("does not let a prefix match a longer segment", () => {
    // `/administration` is not the admin zone; a naive startsWith would claim it.
    expect(zoneFromPathname("/administration")).toBe("web");
    expect(zoneFromPathname("/drafts")).toBe("web");
  });
});

describe("pickMessages", () => {
  it("ships the zone's namespaces and nothing else", () => {
    for (const zone of ZONES) {
      const picked = pickMessages(en, zone);
      expect(Object.keys(picked).sort()).toEqual([...ZONE_NAMESPACES[zone]].sort());
    }
  });

  it("aliases sub-trees instead of copying them", () => {
    // A copy would double the peak memory of every SSR render for no gain.
    const picked = pickMessages(en, "web");
    expect(picked.common).toBe(en.common);
  });

  it("actually narrows: admin-only namespaces never reach the public bundle", () => {
    const web = new Set(ZONE_NAMESPACES.web);
    // Each of these is reachable only from `app/admin` and is the reason the
    // split exists — together they are the bulk of what a visitor was paying for.
    for (const namespace of ["draftAdmin", "registrationFormAdmin", "quota", "subscriptionProviders"]) {
      expect(namespace in en).toBe(true);
      expect(web.has(namespace)).toBe(false);
    }
  });

  it("keeps the public bundle materially smaller than the whole tree", () => {
    const full = JSON.stringify(en).length;
    const web = JSON.stringify(pickMessages(en, "web")).length;
    // Measured at ~24% smaller. The floor guards against a change that quietly
    // widens the web bundle back to everything.
    expect(web).toBeLessThan(full * 0.85);
  });
});

describe("bundle coverage", () => {
  it("assigns every namespace to at least one zone", () => {
    const assigned = new Set(ZONES.flatMap((zone) => [...ZONE_NAMESPACES[zone]]));
    // An unassigned namespace is dead weight in the dictionaries: nothing can
    // render it, because no zone ever ships it.
    expect(Object.keys(en).filter((namespace) => !assigned.has(namespace))).toEqual([]);
  });

  it("never lists a namespace the dictionaries do not define", () => {
    for (const zone of ZONES) {
      expect([...ZONE_NAMESPACES[zone]].filter((namespace) => !(namespace in en))).toEqual([]);
    }
  });

  it("puts the root layout's own chrome in every bundle", () => {
    // `app/layout.tsx` renders the auth modal, account settings, the cookie
    // notice and the toaster OUTSIDE `{children}`, so they render under whatever
    // zone bundle the request selected. A namespace they need that is missing
    // from one zone shows dotted keys on every page of that zone.
    for (const namespace of ["common", "accountSettings", "auth", "nav"]) {
      for (const zone of ZONES) {
        expect(ZONE_NAMESPACES[zone]).toContain(namespace);
      }
    }
  });
});
