#!/usr/bin/env node
// Zone-boundary gate for frontend/src.
//
// The app is one Next deployable split into route zones. The zones only stay
// separable if nothing quietly reaches across them, and nothing that is
// supposed to be shared depends on a route. ESLint cannot state this: its
// `no-restricted-imports` matches the specifier *string*, so `../../admin/x`
// slips through every glob, and eslint-plugin-import's path zones need a
// resolver that understands the `@/*` alias. This resolves both forms itself.
//
// Rules (see docs/frontend-zones.md):
//   Z1  a route zone must not import another route zone
//   Z2  nothing outside src/app may import from src/app
//   Z3  src/components/admin is admin-private
//   Z4  i18n zone bundles cover every namespace their zone can reach
//
// Usage: node scripts/check-zone-boundaries.mjs [--json] [--graph]
//        node scripts/check-zone-boundaries.mjs --write-i18n   # regenerate Z4's map

import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL("../src/", import.meta.url)).replace(/[\\/]$/, "");
const norm = (p) => p.replaceAll("\\", "/");
const CODE = /\.(ts|tsx)$/;

/**
 * Import-ish specifier positions. Three things a naive `from "…"` scan misses
 * and each is a real cross-zone edge: a side-effect `import "…/x.css"`, a
 * dynamic `import("…")`, and `vi.mock`/`mock.module` — a test that mocks
 * across a zone couples to it exactly as hard as an import does.
 */
const SPEC =
  /(?:from\s*|import\s*|import\s*\(\s*|require\s*\(\s*|(?:vi|jest)\.(?:mock|doMock)\(\s*|mock\.module\(\s*)(["'])([^"']+)\1/g;

/** Route zones, by their first path segment under src/app. */
const ROUTE_ZONES = {
  admin: "admin",
  "(site)": "web",
  balancer: "tools",
  draft: "tools",
};

/**
 * `app/api` (route handlers), `app/actions` (server actions) and `app/bff`
 * (this app's own cookie-authenticated endpoints, the ones the gateway never
 * serves) are Next's server-entry conventions, not zones — any zone may call
 * them, and the Z2 ban on importing out of `src/app` would otherwise force
 * them into `src/`, where Next would stop treating them as entries.
 */
const SHARED_APP_DIRS = ["app/api/", "app/actions/", "app/bff/"];

function files(dir = SRC, out = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) files(p, out);
    else if (CODE.test(e.name)) out.push(norm(p));
  }
  return out;
}

/** src-relative module id, extension stripped, so `@/x` and `./x.tsx` unify. */
const idOf = (abs) => norm(relative(SRC, abs)).replace(CODE, "");

function resolveSpec(spec, fromFile) {
  if (spec.startsWith("@/")) return idOf(join(SRC, spec.slice(2)));
  if (spec.startsWith(".")) return idOf(resolve(dirname(fromFile), spec));
  return null; // package
}

const zoneOf = (id) => {
  if (!id.startsWith("app/")) return null;
  const segment = id.slice(4).split("/")[0];
  return ROUTE_ZONES[segment] ?? "root";
};

const findings = [];
const graph = [];
/** module id -> Set of message namespaces it could address */
const mentions = new Map();
/** module id -> Set of module ids it imports */
const edges = new Map();

const MESSAGES = join(SRC, "i18n/messages/en.json");
const NAMESPACES = Object.keys(JSON.parse(readFileSync(MESSAGES, "utf8")));
const isTest = (id) => /\.(test|spec)\.|\.behavior\./.test(id);

/**
 * Deliberately loose. The dominant call-site idiom is a bare `useTranslations()`
 * plus absolute dotted keys — `t("users.profile.title")` — and some of those
 * keys are built from template literals, so no analysis can prove which
 * namespaces a module needs. Matching any quoted `"<namespace>"` or
 * `"<namespace>.` therefore over-collects on purpose: an extra namespace in a
 * zone bundle costs payload, a missing one renders the raw dotted key to a
 * user. Only the safe direction of the error is acceptable.
 */
const MENTION = NAMESPACES.map((ns) => [ns, new RegExp(`["'\`]${ns}[."'\`]`)]);

for (const file of files()) {
  const from = idOf(file);
  const fromZone = zoneOf(from);
  const source = readFileSync(file, "utf8");
  const deps = new Set();

  if (!isTest(from)) {
    const found = new Set();
    for (const [ns, re] of MENTION) if (re.test(source)) found.add(ns);
    if (found.size > 0) mentions.set(from, found);
  }

  for (const [, , spec] of source.matchAll(SPEC)) {
    const to = resolveSpec(spec, file);
    if (to === null) continue;
    graph.push([from, to]);
    if (!isTest(to)) deps.add(to);

    const inAdmin = from.startsWith("app/admin/") || from.startsWith("components/admin/");
    if (to.startsWith("components/admin/") && !inAdmin) {
      findings.push({ rule: "Z3", from, to, what: "components/admin is admin-private" });
    }

    const toZone = zoneOf(to);
    if (toZone === null || toZone === "root") continue;
    if (SHARED_APP_DIRS.some((d) => to.startsWith(d))) continue;

    if (fromZone === null) {
      // The one legal exception: components/admin is admin's own component
      // library, so it may reach into the admin routes it exists to serve.
      if (from.startsWith("components/admin/") && to.startsWith("app/admin/")) continue;
      findings.push({ rule: "Z2", from, to, what: "shared code imports a route" });
    } else if (fromZone !== "root" && fromZone !== toZone) {
      findings.push({ rule: "Z1", from, to, what: `zone ${fromZone} imports zone ${toZone}` });
    }
  }
  edges.set(from, deps);
}

// ---------------------------------------------------------------- Z4: i18n
//
// `src/i18n/request.ts` hands the client only its zone's namespaces, so each
// bundle must be a superset of every namespace reachable from that zone's route
// entries. The map is committed data (runtime cannot walk the import graph);
// this recomputes it and fails on drift. `--write-i18n` regenerates it.

const ZONE_FILE = join(SRC, "i18n/zone-namespaces.json");
const ZONES = ["web", "admin", "tools"];

function reachableFrom(seeds) {
  const seen = new Set();
  const stack = [...seeds];
  while (stack.length > 0) {
    const id = stack.pop();
    if (seen.has(id)) continue;
    seen.add(id);
    for (const dep of edges.get(id) ?? []) stack.push(dep);
  }
  return seen;
}

const seeds = { web: [], admin: [], tools: [], root: [] };
for (const id of edges.keys()) {
  if (isTest(id) || !id.startsWith("app/")) continue;
  if (SHARED_APP_DIRS.some((d) => id.startsWith(d))) continue;
  seeds[zoneOf(id)]?.push(id);
}

// The root layout's chrome (auth modal, account settings, cookie notice,
// toaster) renders on every page under every zone, so its namespaces belong to
// all three bundles rather than a fourth one nothing would select.
const rootNamespaces = new Set();
for (const id of reachableFrom(seeds.root)) for (const ns of mentions.get(id) ?? []) rootNamespaces.add(ns);

const expected = {};
for (const zone of ZONES) {
  const set = new Set(rootNamespaces);
  for (const id of reachableFrom(seeds[zone])) for (const ns of mentions.get(id) ?? []) set.add(ns);
  expected[zone] = [...set].sort();
}

if (process.argv.includes("--write-i18n")) {
  writeFileSync(ZONE_FILE, `${JSON.stringify(expected, null, 2)}\n`);
  const total = JSON.stringify(JSON.parse(readFileSync(MESSAGES, "utf8"))).length;
  console.log(`wrote ${relative(SRC, ZONE_FILE)}`);
  for (const zone of ZONES) {
    console.log(`  ${zone.padEnd(6)} ${String(expected[zone].length).padStart(2)}/${NAMESPACES.length} namespaces`);
  }
  console.log(`  full en bundle: ${(total / 1024).toFixed(0)} kB compact`);
  process.exit(0);
}

let committed = null;
try {
  committed = JSON.parse(readFileSync(ZONE_FILE, "utf8"));
} catch {
  findings.push({ rule: "Z4", from: relative(SRC, ZONE_FILE), to: "(missing)", what: "run --write-i18n" });
}
if (committed !== null) {
  const unassigned = NAMESPACES.filter((ns) => !ZONES.some((z) => committed[z]?.includes(ns)));
  for (const ns of unassigned) {
    findings.push({ rule: "Z4", from: `namespace ${ns}`, to: "(no zone)", what: "dead namespace or missing assignment" });
  }
  for (const zone of ZONES) {
    const have = new Set(committed[zone] ?? []);
    for (const ns of expected[zone]) {
      if (!have.has(ns)) findings.push({ rule: "Z4", from: `${zone} bundle`, to: ns, what: "reachable but not shipped" });
    }
    for (const ns of have) {
      if (!expected[zone].includes(ns)) findings.push({ rule: "Z4", from: `${zone} bundle`, to: ns, what: "shipped but unreachable" });
    }
  }
}

if (process.argv.includes("--graph")) {
  console.log(JSON.stringify(graph, null, 2));
} else if (process.argv.includes("--json")) {
  console.log(JSON.stringify(findings, null, 2));
} else {
  const RULES = [
    ["Z1", "a route zone must not import another route zone"],
    ["Z2", "nothing outside src/app may import from src/app"],
    ["Z3", "src/components/admin is admin-private"],
    ["Z4", "i18n zone bundles cover every reachable namespace"],
  ];
  for (const [id, what] of RULES) {
    const hits = findings.filter((f) => f.rule === id);
    console.log(`${hits.length === 0 ? "PASS" : "FAIL"}  ${id}  ${String(hits.length).padStart(4)}  ${what}`);
    for (const f of hits.slice(0, 20)) console.log(`        ${f.from}\n          -> ${f.to}  (${f.what})`);
    if (hits.length > 20) console.log(`        … ${hits.length - 20} more`);
  }
  console.log(`\n${findings.length} violation(s)`);
}

process.exit(findings.length === 0 ? 0 : 1);
