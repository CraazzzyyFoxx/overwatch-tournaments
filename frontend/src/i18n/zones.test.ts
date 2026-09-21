import { describe, expect, it } from "bun:test";

import en from "./messages/en.json";
import ZONE_NAMESPACES from "./zone-namespaces.json";
import { pickMessages, ZONES } from "./zones";

/**
 * The bundle *contents* are generated and drift-checked by
 * `scripts/check-zone-boundaries.mjs` (rule Z4) — it walks the import graph,
 * which a unit test cannot. What is tested here is the runtime half: that the
 * picker narrows, and the invariant that makes narrowing safe at all (a zone
 * provider replaces the root one, so every zone must carry the root bundle).
 */

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

  it("makes every zone bundle a superset of the root one", () => {
    // `app/layout.tsx` mounts `zone="root"` for the chrome it renders outside
    // `{children}` (auth modal, account settings, cookie notice, toaster), and
    // each zone layout mounts its own provider INSIDE it. `use-intl`'s
    // IntlProvider replaces `messages` instead of merging, so a root namespace
    // missing from a zone shows dotted keys on every page of that zone.
    for (const zone of ZONES) {
      const have = new Set(ZONE_NAMESPACES[zone]);
      expect(ZONE_NAMESPACES.root.filter((namespace) => !have.has(namespace))).toEqual([]);
    }
  });
});
