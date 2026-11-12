import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import { en as kitEn } from "@craazzzyyfoxx/admin-kit/messages";

import appEn from "./messages/en.json";
import ZONE_NAMESPACES from "./zone-namespaces.json";
import { pickMessages, ZONES } from "./zones";

// What `request.ts` serves: the app's tree plus the kit's `adminKit` namespace.
const en = { ...appEn, ...kitEn };

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
      // A dotted entry (`"pickBan.rules.preset"`) ships part of its namespace.
      expect(Object.keys(picked).sort()).toEqual([...new Set(ZONE_NAMESPACES[zone].map((entry) => entry.split(".")[0]))].sort());
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

  it("keeps module slot families apart: a host ships only the namespaces of the slots it can render", () => {
    // The admin slot family (division editor, collector mapping) must not widen the public bundle, and the
    // pre-game bans slot must not widen the balancer/draft one (their rank-history host reaches only its own family).
    for (const namespace of ["adminSettings", "collectors"]) {
      expect(namespace in en).toBe(true);
      expect(ZONE_NAMESPACES.web).not.toContain(namespace);
      expect(ZONE_NAMESPACES.tools).not.toContain(namespace);
    }
    expect(ZONE_NAMESPACES.tools).not.toContain("pickBan");
    expect(ZONE_NAMESPACES.web).toContain("pickBan.room");
  });

  it("ships a dotted entry as just that subtree, under its own key path", () => {
    // The mix header and account settings render in tools (and root): the preset names and two labels, not the
    // ~33 kB constructor copy. Tools also ships the room copy, for the shared ban board in a mix room; root does not.
    expect(ZONE_NAMESPACES.tools).toEqual(expect.arrayContaining(["pickBan.mixBans", "pickBan.rules.preset"]));
    const tools = pickMessages(en, "tools");
    const t = createTranslator({ locale: "en", messages: tools as typeof en });

    expect(t("pickBan.rules.preset.hero_classic")).toBe(en.pickBan.rules.preset.hero_classic);
    expect(t("pickBan.mixBans.none")).toBe(en.pickBan.mixBans.none);
    expect(tools.pickBan?.rules.preset).toBe(en.pickBan.rules.preset);
    expect(Object.keys(tools.pickBan ?? {}).sort()).toEqual(["mixBans", "room", "rules"]);
    expect(Object.keys(tools.pickBan?.rules ?? {})).toEqual(["preset"]);
    expect(Object.keys(pickMessages(en, "root").pickBan ?? {}).sort()).toEqual(["mixBans", "rules"]);
    // Projected into fresh nodes: the shared tree keeps everything.
    expect(Object.keys(en.pickBan.rules)).toContain("summary");
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
    const assigned = new Set(ZONES.flatMap((zone) => ZONE_NAMESPACES[zone].map((entry) => entry.split(".")[0])));
    // An unassigned namespace is dead weight in the dictionaries: nothing can
    // render it, because no zone ever ships it.
    expect(Object.keys(en).filter((namespace) => !assigned.has(namespace))).toEqual([]);
  });

  it("never lists a namespace or subtree the dictionaries do not define", () => {
    const defined = (entry: string) => {
      let node: unknown = en;
      for (const key of entry.split(".")) {
        if (node === null || typeof node !== "object" || !Object.hasOwn(node, key)) return false;
        node = (node as Record<string, unknown>)[key];
      }
      return true;
    };
    for (const zone of ZONES) {
      expect(ZONE_NAMESPACES[zone].filter((entry) => !defined(entry))).toEqual([]);
    }
  });

  it("makes every zone bundle a superset of the root one", () => {
    // `app/layout.tsx` mounts `zone="root"` for the chrome it renders outside
    // `{children}` (auth modal, account settings, cookie notice, toaster), and
    // each zone layout mounts its own provider INSIDE it. `use-intl`'s
    // IntlProvider replaces `messages` instead of merging, so a root namespace
    // missing from a zone shows dotted keys on every page of that zone.
    for (const zone of ZONES) {
      const have = ZONE_NAMESPACES[zone];
      // Listed itself, or inside a shorter entry (`pickBan` ships `pickBan.mixBans`).
      const ships = (entry: string) => have.some((other) => entry === other || entry.startsWith(`${other}.`));
      expect(ZONE_NAMESPACES.root.filter((entry) => !ships(entry))).toEqual([]);
    }
  });
});
