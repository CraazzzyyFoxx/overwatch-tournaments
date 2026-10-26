import type { Page } from "@playwright/test";
import { Api } from "../support/api";
import { BASE_URL, COOKIE_PREFIX } from "../support/env";
import { expect, test } from "../support/fixtures";
import { seedBracket } from "../support/flows";
import { type Auth, ROUTES, type Route } from "../support/route-table";
import { createTournament, uniq } from "../support/seed";
import { createUser, type TestUser } from "../support/users";

// Auth/permission matrix over every gateway route (support/route-table.ts,
// generated from the edge.RouteSpec tables by e2e/scripts/gen-route-table.ts).
// One test per (route table × caller); each route is probed and every wrong
// verdict is reported on its own line (expect.soft), so a run itemizes the
// whole regression surface. Non-failing oddities (a 404 where 403 was due,
// validation before authz, 2xx on a nonexistent id) are test annotations.

const GHOST = 999_999_999;

/** Real ids from one seeded live bracket; the probes put them in paths, the `workspace_id`/`tournament_id` query and the body. */
type Ids = { workspace: number; tournament: number; stage: number; stageItem: number; encounter: number; team: number; player: number };

// Path params that are enums, not ids: always a real value, so the handler gets
// past validation to the entity lookup.
const ENUMS: Record<string, string> = {
  discipline: "overwatch",
  provider: "discord",
  slot: "logo",
  scope: "registration",
  asset_type: "heroes",
  position: "1",
};

// AuthRequired routes any signed-in user may call on their own behalf, so a
// non-member legitimately gets past authz. Own-account auth routes are also
// destructive for the probing session (logout, DELETE /auth/me).
const SELF_SERVICE: RegExp[] = [
  /^\/api\/v1\/auth\/(?!rbac\/|service\/)/,
  /^\/api\/v1\/(balancer\/)?me\//,
  /^\/api\/v1\/notifications/,
  /^\/api\/v1\/encounters\/views/,
  /^\/api\/v1\/workspaces$/, // self-create, capped (app-service rpc/workspaces.py _create: workspace.self_create capability)
  /\/registration(\/me(\/.*)?)?$/,
  /\/registration-teams$/,
  /\/registration-teams\/(my-invites|free-agents)$/, // free agents: any account, by design (public_rpc.py regteam_free_agents)
  /\/registration-teams\/invites\/(accept|decline)$/,
  /\/members\/me$/,
  /\/custom-games\/\{game_id\}\/me$/,
  /\/my-role$/,
  /\/subscription\/(me|redeem-code)$/,
];

/** The real seeded id for a path param, or undefined (-> a nonexistent id). */
function realId(ids: Ids, route: Route, parent: string | undefined, name: string): number | undefined {
  switch (name) {
    case "workspace_id":
      return ids.workspace;
    case "tournament_id":
      return ids.tournament;
    case "stage_id":
      return ids.stage;
    case "stage_item_id":
      return ids.stageItem;
    case "encounter_id":
      return ids.encounter;
    case "team_id": // registration-teams and draft teams are other entities
      return route.pattern.startsWith("/api/v1/admin/teams/") ? ids.team : undefined;
    case "id":
      return { workspaces: ids.workspace, tournaments: ids.tournament, encounters: ids.encounter, teams: ids.team, users: ids.player }[
        parent ?? ""
      ];
  }
  return undefined;
}

/** Fills path params from `ids` (null = every id nonexistent). `ghosted`: some id param got a nonexistent value. */
function fill(route: Route, ids: Ids | null): { url: string; ghosted: boolean } {
  let ghosted = false;
  const url = route.pattern.replace(/(?:\/([\w-]+))?\/\{(\w+)\}/g, (_, parent: string | undefined, name: string) => {
    const prefix = parent ? `/${parent}` : "";
    if (name === "kind") return `${prefix}/${route.pattern.includes("/pick-ban/") ? "map" : "character"}`;
    if (ENUMS[name]) return `${prefix}/${ENUMS[name]}`;
    const real = ids ? realId(ids, route, parent, name) : undefined;
    if (real === undefined) ghosted = true;
    return `${prefix}/${real ?? (["token", "name", "key", "slug"].includes(name) ? "e2e-nonexistent" : GHOST)}`;
  });
  return { url, ghosted };
}

type Hit = { status: number; body: string };

async function hit(api: Api, route: Route, url: string, ids: Ids | null): Promise<Hit> {
  // Scope ids ride along so workspace-scoped handlers reach their authz check
  // instead of failing closed on a missing workspace_id.
  const scope = { workspace_id: ids?.workspace ?? GHOST, tournament_id: ids?.tournament ?? GHOST };
  const write = route.method === "POST" || route.method === "PUT" || route.method === "PATCH";
  try {
    const res = await api.raw(route.method, url, { query: scope, body: write ? scope : undefined });
    return { status: res.status(), body: (await res.text()).slice(0, 400) };
  } catch (error) {
    return { status: 0, body: `no response: ${String(error).split("\n")[0]}` };
  }
}

/** Runs `fn` over `items`, `width` at a time. */
async function each<T>(items: T[], fn: (item: T) => Promise<void>, width = 8) {
  const queue = [...items];
  await Promise.all(
    Array.from({ length: width }, async () => {
      for (let item = queue.shift(); item; item = queue.shift()) await fn(item);
    })
  );
}

let ids: Ids;
let hiddenTournament: number;
let outsider: Omit<TestUser, "api">;

test.beforeAll(async ({ admin }) => {
  const api = await Api.create(admin.accessToken);
  const seed = await seedBracket(api, { teams: 4 });
  const encounter = seed.encounters.find((e) => e.teams.every((t) => t.team_id)) ?? seed.encounters[0];
  ids = {
    workspace: seed.workspace.id,
    tournament: seed.tournament.id,
    stage: seed.stage.id,
    stageItem: seed.stage.items[0].id,
    encounter: encounter.id,
    team: seed.teams[0].id,
    player: seed.teams[0].players[0].user_id,
  };
  hiddenTournament = (await createTournament(api, seed.workspace.id, { is_hidden: true })).id;
  const { api: userApi, ...user } = await createUser({ prefix: "outsider" });
  outsider = user;
  await Promise.all([api.dispose(), userApi.dispose()]);
});

type Caller = "anonymous" | "outsider" | "admin";
type Verdict = { fail?: string; note?: string } | undefined;
type Probe = {
  title: string;
  caller: Caller;
  /** false: every id param gets a nonexistent value. */
  seeded: boolean;
  applies: (r: Route) => boolean;
  judge: (r: Route, hit: Hit) => Verdict;
};

const is5xx = (status: number) => status === 0 || status >= 500;

const PROBES: Probe[] = [
  {
    // AuthRequired -> 401 at the gateway; public routes -> never 401 on a read, never 5xx.
    title: "anonymous",
    caller: "anonymous",
    seeded: true,
    applies: () => true,
    judge: (r, { status }) => {
      if (r.auth === "required") return status === 401 ? undefined : { fail: "expected 401 for anonymous on an AuthRequired route" };
      if (is5xx(status)) return { fail: "server error for anonymous" };
      if (r.method === "GET" && status === 401) return { fail: `AuthMode ${r.auth} route answered 401 to anonymous` };
      return undefined;
    },
  },
  {
    // A signed-in user with no role in the seeded workspace: authz must refuse.
    title: "non-member",
    caller: "outsider",
    seeded: true,
    applies: (r) => r.auth === "required" && !SELF_SERVICE.some((re) => re.test(r.pattern)),
    judge: (r, { status }) => {
      if (status === 403) return undefined;
      // Service-to-service routes take a service token: a user JWT is no credential there.
      if (status === 401 && r.pattern.startsWith("/api/v1/auth/service/")) return undefined;
      if (status === 404) return { note: "404 (existence hidden or checked before authz)" };
      if (status === 400 || status === 422) return { note: `${status} (validated before authz)` };
      if (status >= 200 && status < 300) return { fail: "non-member was allowed" };
      return { fail: "expected 403/404 for a non-member" };
    },
  },
  {
    // Nonexistent ids must be a clean 404/422, never a handler crash.
    title: "superuser on nonexistent ids",
    caller: "admin",
    seeded: false,
    applies: (r) => fill(r, null).ghosted,
    judge: (_r, { status }) => {
      if (is5xx(status)) return { fail: "server error on a nonexistent id" };
      if (status === 404 || status === 422) return undefined;
      return { note: `${status} on a nonexistent id` };
    },
  },
  {
    // Every read against the seeded live bracket, as superuser.
    title: "superuser reads on seeded ids",
    caller: "admin",
    seeded: true,
    applies: (r) => r.method === "GET",
    judge: (_r, { status }) => (is5xx(status) ? { fail: "server error on a read" } : undefined),
  },
];

for (const [table, routes] of Map.groupBy(ROUTES, (r) => r.table)) {
  test.describe(table, () => {
    for (const probe of PROBES) {
      const targets = routes.filter(probe.applies);
      if (!targets.length) continue;
      test(probe.title, async ({ adminApi, anonApi }) => {
        test.fixme(
          table === "discord.Routes" && probe.caller !== "anonymous",
          "discord-service is not part of the e2e stack: its RPC queue has no consumer, so every authenticated call 504s after 120 s"
        );
        const outsiderApi = await Api.create(outsider.accessToken);
        const api = { anonymous: anonApi, outsider: outsiderApi, admin: adminApi }[probe.caller];
        const scope = probe.seeded ? ids : null;
        const run = async (route: Route) => {
          const { url } = fill(route, scope);
          const res = await hit(api, route, url, scope);
          const verdict = probe.judge(route, res);
          const line = `${route.method} ${url} -> ${res.status} ${res.body}`;
          if (verdict?.note) test.info().annotations.push({ type: verdict.note, description: line });
          expect.soft(verdict?.fail, `${route.method} ${route.pattern} [${route.auth}]: ${verdict?.fail}\n  ${line}`).toBeUndefined();
        };
        // Destructive verbs last: if authz is broken they would delete the seed.
        await each(targets.filter((r) => r.method !== "DELETE"), run);
        await each(targets.filter((r) => r.method === "DELETE"), run);
        await outsiderApi.dispose();
      });
    }
  });
}

// The matrix sends a scope-only body, so routes that validate the body before
// authz answer 422 and never reach the permission check. For the escalation-
// critical ones, a schema-valid body proves the refusal is about permission.
test("non-member with a schema-valid body is still refused", async () => {
  const api = await Api.create(outsider.accessToken);
  const cases: [string, string, Record<string, unknown>][] = [
    ["POST", "/api/v1/auth/rbac/roles", { name: uniq("escalate"), permission_ids: [] }],
    ["POST", "/api/v1/auth/rbac/permissions", { name: uniq("e2e.perm"), resource: "e2e", action: "probe" }],
    ["POST", "/api/v1/auth/rbac/users/assign-role", { user_id: outsider.id, role_id: 1, workspace_id: ids.workspace }],
    ["POST", "/api/v1/admin/announcements", { audience: "global", default_locale: "en", locales: { en: { title: "x", body: "x" } } }],
    ["POST", "/api/v1/achievement/calculate", { discipline: "overwatch", workspace_id: ids.workspace }],
    ["POST", `/api/v1/achievement/calculate/${ids.tournament}`, { discipline: "overwatch" }],
    ["POST", "/api/v1/admin/players", { team_id: ids.team, name: uniq("p"), user_id: ids.player }],
    ["POST", `/api/v1/encounters/${ids.encounter}/report`, { games_played: 1 }],
    ["POST", `/api/v1/encounters/${ids.encounter}/pick-ban/map/elect-opener`, { first_team_id: ids.team }],
    ["POST", `/api/v1/encounters/${ids.encounter}/chat`, { body: "outsider" }],
    ["PATCH", `/api/v1/encounters/${ids.encounter}/chat/settings`, { spectators_can_read: true }],
  ];
  for (const [method, url, body] of cases) {
    const res = await api.raw(method, url, { body });
    expect.soft(res.status(), `${method} ${url} -> ${res.status()} ${(await res.text()).slice(0, 300)}`).toBe(403);
  }
  await api.dispose();
});

test("drift guard: every documented gateway route is classified in route-table.ts", async ({ anonApi }) => {
  const known = new Map(ROUTES.map((r) => [`${r.method} ${r.pattern}`, r.auth]));
  const missing: string[] = [];
  const drifted: string[] = [];
  for (const spec of ["/api/openapi.json", "/api/openapi.admin.json"]) {
    const doc = await anonApi.get<{ paths: Record<string, Record<string, { security: Record<string, unknown>[] }>> }>(spec);
    for (const [path, ops] of Object.entries(doc.paths)) {
      for (const [method, op] of Object.entries(ops)) {
        const key = `${method.toUpperCase()} ${path}`;
        const auth: Auth = !op.security.length ? "none" : op.security.some((s) => !Object.keys(s).length) ? "optional" : "required";
        if (!known.has(key)) missing.push(`${key} (${auth})`);
        else if (known.get(key) !== auth) drifted.push(`${key}: table=${known.get(key)} live=${auth}`);
      }
    }
  }
  const regen = "regenerate with `bun e2e/scripts/gen-route-table.ts` and classify the route";
  expect(missing, `live routes missing from route-table.ts — ${regen}`).toEqual([]);
  expect(drifted, `auth mode changed since route-table.ts was generated — ${regen}`).toEqual([]);
});

test("removed endpoints stay removed", async ({ adminApi }) => {
  const removed: [string, string][] = [
    ["POST", "/api/v1/analytics/openskill"],
    ["POST", "/api/v1/analytics/train"],
    ["POST", "/api/v1/analytics/infer"],
    ["PATCH", `/api/v1/auth/player/linked/${GHOST}/primary`],
    ["GET", `/api/v1/catalog/legacy/character/${GHOST}`],
  ];
  for (const [method, url] of removed) {
    const res = await adminApi.raw(method, url, { body: method === "GET" ? undefined : {} });
    expect.soft([404, 405], `${method} ${url} -> ${res.status()} ${(await res.text()).slice(0, 300)}`).toContain(res.status());
  }
});

type Frame = { op: string; topic?: string; code?: string; message?: string };

/**
 * Opens /ws from the browser (a real Origin, like the product) and returns the
 * server's verdict on one subscribe. Node's own WebSocket left the Windows
 * worker dying on a libuv assertion at exit. The socket authenticates the way
 * the site does: the access-token cookie rides the handshake (the gateway
 * ignores `?token=`); no token means no cookie, i.e. anonymous.
 */
async function subscribe(page: Page, topic: string, token?: string): Promise<Frame> {
  const url = `${BASE_URL.replace(/^http/, "ws")}/ws`;
  const cookie = `${COOKIE_PREFIX}_access_token`;
  await page.context().clearCookies({ name: cookie });
  if (token) await page.context().addCookies([{ name: cookie, value: token, url: BASE_URL }]);
  return page.evaluate(
    async ({ url, topic }) => {
      const ws = new WebSocket(url);
      const verdict = Promise.withResolvers<Frame>();
      const closed = Promise.withResolvers<void>();
      ws.onopen = () => ws.send(JSON.stringify({ op: "subscribe", topic }));
      ws.onmessage = (e) => {
        const frame = JSON.parse(String(e.data)) as Frame;
        if ((frame.op === "subscribed" || frame.op === "error") && (!frame.topic || frame.topic === topic)) verdict.resolve(frame);
      };
      ws.onclose = (e) => {
        verdict.reject(new Error(`websocket closed (${e.code} ${e.reason}) before a verdict on ${topic}`));
        closed.resolve();
      };
      const timer = setTimeout(() => verdict.reject(new Error(`no subscribe verdict for ${topic} within 15s`)), 15_000);
      try {
        return await verdict.promise;
      } finally {
        clearTimeout(timer);
        ws.close();
        await closed.promise;
      }
    },
    { url, topic }
  );
}

test("websocket: anonymous spectates a visible tournament's bracket, not a hidden one's", async ({ admin, page }) => {
  await page.goto("/api/v1/disciplines"); // any gateway document: gives the page the allowed Origin without a Next compile
  expect(await subscribe(page, `tournament:${ids.tournament}:bracket`), "anonymous subscribe to a visible tournament's bracket").toMatchObject({
    op: "subscribed",
  });
  const hidden = `tournament:${hiddenTournament}:bracket`;
  expect(await subscribe(page, hidden), "anonymous subscribe to a HIDDEN tournament's bracket").toMatchObject({
    op: "error",
    code: "auth_required",
  });
  expect(await subscribe(page, hidden, outsider.accessToken), "non-member subscribe to a hidden tournament").toMatchObject({
    op: "error",
    code: "forbidden",
  });
  // Control: the denial is about visibility, not a broken topic.
  expect(await subscribe(page, hidden, admin.accessToken), "superuser subscribe to a hidden tournament").toMatchObject({ op: "subscribed" });
});
