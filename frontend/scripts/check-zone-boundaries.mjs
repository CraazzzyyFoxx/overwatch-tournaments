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
//   Z5  every zone layout mounts its own i18n bundle
//   Z6  outside src/disciplines, only disciplines/{types,DisciplineWidget,registry/<family>} are importable
//   Z7  only disciplines/registry/** imports a module (disciplines/<code>/<family>); a module never imports
//       another module, anything under src/app (root entries included) or components/admin
// Test code — exactly `*.test.ts(x)` and src/test/** — is exempt from Z6/Z7's "who may import a module":
// parity oracles reproduce module helpers. Runtime code (harnesses and fixtures included) never is.
//
// Usage: node scripts/check-zone-boundaries.mjs [--json] [--graph] [--src=<dir>]
//        node scripts/check-zone-boundaries.mjs --write-i18n   # regenerate Z4's map

import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const srcArg = process.argv.find((arg) => arg.startsWith("--src="));
const SRC = (srcArg ? resolve(srcArg.slice("--src=".length)) : fileURLToPath(new URL("../src/", import.meta.url))).replace(
  /[\\/]$/,
  ""
);
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

/** A whole `import type X|{…}|* as X from "…"` / `export type {…}|* from "…"` statement. */
const TYPE_ONLY =
  /^[ \t]*(?:import\s+type\s+(?:\{[^}]*\}|\*\s+as\s+[\w$]+|[\w$]+)|export\s+type\s+(?:\{[^}]*\}|\*(?:\s+as\s+[\w$]+)?))\s*from\s*(["'])[^"']+\1;?/gm;

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

const ALL = files();
const IDS = new Set(ALL.map(idOf));

function resolveSpec(spec, fromFile) {
  let id;
  if (spec.startsWith("@/")) id = idOf(join(SRC, spec.slice(2)));
  else if (spec.startsWith(".")) id = idOf(resolve(dirname(fromFile), spec));
  else return null; // package
  // A directory import (`@/components/x`) is its `index`. Without this the edge
  // dangles and Z4 silently loses the whole subtree behind it.
  return IDS.has(id) || !IDS.has(`${id}/index`) ? id : `${id}/index`;
}

const zoneOf = (id) => {
  if (!id.startsWith("app/")) return null;
  const segment = id.slice(4).split("/")[0];
  return ROUTE_ZONES[segment] ?? "root";
};

const findings = [];
const graph = [];
/** The package's own namespace (not in en.json) and the import specifiers that can render it. */
const KIT_NAMESPACE = "adminKit";
const KIT_SPEC = /^@craazzzyyfoxx\/admin-kit\/(?!messages$|styles\.css$)/;

/** module id -> Set of message namespaces it could address */
const mentions = new Map();
/** module id -> Set of module ids it imports */
const edges = new Map();

const MESSAGES = join(SRC, "i18n/messages/en.json");
const EN = JSON.parse(readFileSync(MESSAGES, "utf8"));
const NAMESPACES = Object.keys(EN);
const isTest = (id) => /\.(test|spec)\.|\.behavior\./.test(id);
/** Z6/Z7's exemption, exactly: `*.test.ts(x)` (incl. `*.behavior.test.tsx`) and the shared test support in `src/test/`. */
const isTestCode = (id) => /\.test$/.test(id) || id.startsWith("test/");

/** `disciplines/<code>/…` -> `<code>`; the registry, types and host are not a module. */
const moduleOf = (id) => /^disciplines\/(?!registry\/)([^/]+)\//.exec(id)?.[1] ?? null;

/** Z6/Z7 for one runtime edge, or null. */
function disciplineFinding(from, to) {
  const fromModule = moduleOf(from);
  const toModule = moduleOf(to);
  if (fromModule !== null && toModule !== null && fromModule !== toModule) {
    return { rule: "Z7", from, to, what: "a discipline module imports another module" };
  }
  if (fromModule !== null && to.startsWith("app/")) {
    return { rule: "Z7", from, to, what: "a discipline module imports src/app" };
  }
  if (fromModule !== null && to.startsWith("components/admin/")) {
    return { rule: "Z7", from, to, what: "a discipline module imports components/admin" };
  }
  if (isTestCode(from) || !to.startsWith("disciplines/")) return null;
  if (toModule !== null && toModule === fromModule) return null;
  if (!from.startsWith("disciplines/")) {
    // What code outside `src/disciplines` may import from it: the types, the host and a family registry.
    const port =
      to === "disciplines/types" ||
      to === "disciplines/DisciplineWidget" ||
      (/^disciplines\/registry\/[^/]+$/.test(to) && to !== "disciplines/registry/create");
    return port ? null : { rule: "Z6", from, to, what: "import disciplines/types, DisciplineWidget or registry/<family>" };
  }
  if (toModule !== null && !(from.startsWith("disciplines/registry/") && /^disciplines\/[^/]+\/[^/]+$/.test(to))) {
    return { rule: "Z7", from, to, what: "only disciplines/registry/* imports a module's <family> entrypoint" };
  }
  return null;
}

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

/**
 * Namespaces a zone may ship by subtree. For these a mention's dotted literal
 * (`"pickBan.rules.preset"`, or the static head of `` `pickBan.room.${key}` ``)
 * is what the module needs, and a zone ships the union of its modules'
 * subtrees -- the whole namespace only when one of them names it bare. The mix
 * header and account settings render in the tools and root zones and need two
 * labels and the preset names, not the ~33 kB constructor and room copy.
 */
const SPLIT = new Map(
  ["pickBan"].map((ns) => [ns, new RegExp(`["'\`](${ns}(?:\\.[A-Za-z0-9_]+)*)(?=[."'\`])`, "g")]),
);

/** The deepest message node a dotted literal names: a full key ships itself, a literal past the tree its parent. */
function messageNode(path) {
  const keys = path.split(".");
  let node = EN;
  let depth = 0;
  while (depth < keys.length && node !== null && typeof node === "object" && keys[depth] in node) {
    node = node[keys[depth]];
    depth += 1;
  }
  return keys.slice(0, Math.max(depth, 1)).join(".");
}

/** Bare namespaces win over their subtrees, and a subtree over its own descendants. */
function normalized(entries) {
  const all = [...new Set(entries)];
  return all.filter((entry) => !all.some((other) => entry.startsWith(`${other}.`))).sort();
}

for (const file of ALL) {
  const from = idOf(file);
  const fromZone = zoneOf(from);
  const source = readFileSync(file, "utf8");
  const deps = new Set();

  // Query-key factories hold cache keys, never message keys: `["teams", id]` is not the `teams` namespace.
  if (!isTest(from) && !/(^|\/)query-keys$/.test(from)) {
    const found = new Set();
    for (const [ns, re] of MENTION) {
      if (!re.test(source)) continue;
      const split = SPLIT.get(ns);
      if (split === undefined) found.add(ns);
      else for (const [, path] of source.matchAll(split)) found.add(messageNode(path));
    }
    if (found.size > 0) mentions.set(from, found);
  }

  // `import type` / `export type … from` are erased at compile time: they put nothing in a
  // zone's runtime graph, so they carry no namespaces either (the generated OpenAPI types
  // mention every message-namespace word as a schema name).
  for (const [, , spec] of source.replace(TYPE_ONLY, "").matchAll(SPEC)) {
    const to = resolveSpec(spec, file);
    if (to === null) {
      // `@craazzzyyfoxx/admin-kit` reads its strings from the `adminKit` namespace, merged into the
      // messages in `i18n/request.ts` (it is not in en.json). Any runtime import of the package may
      // render them; over-collected on purpose, like every other mention (~4 kB per bundle).
      if (KIT_SPEC.test(spec) && !isTest(from)) mentions.set(from, (mentions.get(from) ?? new Set()).add(KIT_NAMESPACE));
      continue;
    }
    graph.push([from, to]);
    if (!isTest(to)) deps.add(to);

    const discipline = disciplineFinding(from, to);
    if (discipline !== null) findings.push(discipline);

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
// Each zone layout hands the client only its zone's namespaces, so each bundle
// must be a superset of every namespace reachable from that zone's route
// entries. `root` is its own bundle: `app/layout.tsx` renders chrome outside
// `{children}` and is the only provider a root-level page (`not-found`) gets.
// The map is committed data (runtime cannot walk the import graph); this
// recomputes it and fails on drift. `--write-i18n` regenerates it.

const ZONE_FILE = join(SRC, "i18n/zone-namespaces.json");
const ZONES = ["root", "web", "admin", "tools"];

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
// toaster) renders on every page under every zone, so its namespaces are in
// every bundle as well as in `root`: a zone provider REPLACES the root one for
// everything under it (`use-intl`'s IntlProvider does not merge messages).
const rootNamespaces = new Set();
for (const id of reachableFrom(seeds.root)) for (const ns of mentions.get(id) ?? []) rootNamespaces.add(ns);

const expected = {};
for (const zone of ZONES) {
  const set = new Set(rootNamespaces);
  for (const id of reachableFrom(seeds[zone])) for (const ns of mentions.get(id) ?? []) set.add(ns);
  expected[zone] = normalized([...set]);
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
  const unassigned = NAMESPACES.filter(
    (ns) => !ZONES.some((z) => committed[z]?.some((entry) => entry === ns || entry.startsWith(`${ns}.`))),
  );
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

// ------------------------------------- Z5: every zone mounts its own bundle
//
// A bundle is only correct if the layout that owns the zone mounts it: a
// client-side navigation re-renders nothing above the deepest shared layout,
// so a zone whose layout does not mount `ZoneIntlProvider` inherits whichever
// bundle the first page load picked and renders dotted keys.

for (const [segment, zone] of [...Object.entries(ROUTE_ZONES), [".", "root"]]) {
  const layout = join(SRC, "app", segment, "layout.tsx");
  let source = "";
  try {
    source = readFileSync(layout, "utf8");
  } catch {
    source = "";
  }
  if (!new RegExp(`ZoneIntlProvider\\s+zone="${zone}"`).test(source)) {
    findings.push({
      rule: "Z5",
      from: `app/${segment}/layout.tsx`,
      to: `zone="${zone}"`,
      what: "layout does not mount its message bundle",
    });
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
    ["Z5", "every zone layout mounts its own message bundle"],
    ["Z6", "outside src/disciplines only types, DisciplineWidget and registry/<family> are importable"],
    ["Z7", "only the registry imports a discipline module; modules stay apart"],
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
