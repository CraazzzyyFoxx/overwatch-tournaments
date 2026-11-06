import { poll } from "../support/api";
import { expect, test } from "../support/fixtures";
import { listTeams, openRegistration, seedPlayers, type BalancerJob } from "../support/flows";
import { createTournament, createWorkspace, nodeOf, transitionNode, type Tournament } from "../support/seed";

// Tournament balancer (schemasplit01: registration pool → balancer job → saved
// balance → tournament teams), the workspace roster and its rank layers.

type Player = { uuid: string; name: string; assigned_rating: number };
type Variant = { teams: { id: number; name: string; roster: Record<string, Player[]> }[]; benched_players: Player[] };
type CreateJob = BalancerJob & { status_url: string; result_url: string };

const SHAPE = { tank: 1, damage: 2, support: 2 };

/**
 * A registered pool of `n` players with the registration closed and the formation `forming`: the state the balancer
 * works in. `formation` is the query every balancer route of the tournament takes.
 */
async function formingPool(api: Parameters<typeof openRegistration>[0], tournamentId: number, n: number) {
  const { registrationNodeId } = await openRegistration(api, tournamentId);
  const players = n > 0 ? await seedPlayers(api, tournamentId, n, { registrationNodeId }) : [];
  const formationNode = await nodeOf(api, tournamentId, "formation");
  await transitionNode(api, registrationNodeId, "closed");
  await transitionNode(api, formationNode.id, "forming");
  return { players, formation: { formation_node_id: formationNode.id } };
}

test("public balancer config answers for every installed game, 404 for an unknown one", async ({ anonApi }) => {
  for (const discipline of ["overwatch", "lol", "deadlock", "valorant"]) {
    const config = await anonApi.get<{ defaults: Record<string, unknown>; presets: Record<string, unknown>; limits: object }>(
      "/api/v1/balancer/config",
      { discipline }
    );
    expect(Object.keys(config.presets), `${discipline} presets`).toContain("DEFAULT");
    expect(config.defaults.population_size, `${discipline} defaults`).toEqual(expect.any(Number));
  }
  const res = await anonApi.raw("GET", "/api/v1/balancer/config", { query: { discipline: "nope" } });
  expect(res.status()).toBe(404);
});

test("tournament balance: config → async job → save → export creates teams → rank-only re-export", async ({ adminApi, makeUser }) => {
  const ws = await createWorkspace(adminApi);
  const t = await createTournament(adminApi, ws.id);
  const { players: pool, formation } = await formingPool(adminApi, t.id, 11);
  const tagById = new Map(pool.map((reg) => [String(reg.id), reg.primary_handle]));

  expect(await adminApi.get(`/api/v1/balancer/tournaments/${t.id}/config`), "no config before the first save").toBeNull();
  await adminApi.put(`/api/v1/balancer/tournaments/${t.id}/config`, { config_json: { generation_count: 80, population_size: 40 } });
  const config = await adminApi.get<{ config_json: Record<string, number> }>(`/api/v1/balancer/tournaments/${t.id}/config`);
  expect(config.config_json).toMatchObject({ generation_count: 80, population_size: 40 });
  expect(await adminApi.get(`/api/v1/balancer/tournaments/${t.id}/summary`)).toMatchObject({ id: t.id, workspace_id: ws.id });

  const job = await adminApi.call<CreateJob>("POST", `/api/v1/balancer/tournaments/${t.id}/balance`, {
    body: { config_overrides: config.config_json },
    query: formation,
    expectStatus: 202,
  });
  // Poll the status URL the 202 advertises, as a client would.
  const status = await poll(
    async () => {
      const s = await adminApi.get<BalancerJob & { tournament_id: number | null }>(job.status_url);
      return s.status === "succeeded" || s.status === "failed" ? s : undefined;
    },
    `balance job ${job.job_id}`,
    120_000
  );
  expect(status.status, `job error: ${status.error}`).toBe("succeeded");
  expect(status.tournament_id).toBe(t.id);

  const outsider = await makeUser("nobal");
  expect((await outsider.api.raw("GET", `/api/v1/balancer/jobs/${job.job_id}/result`)).status(), "foreign job result").toBe(403);

  const { variants } = await adminApi.get<{ variants: Variant[] }>(job.result_url);
  expect(variants.length).toBeGreaterThan(0);
  const variant = variants[0];
  expect(variant.teams).toHaveLength(2);
  for (const team of variant.teams) {
    expect(Object.fromEntries(Object.entries(team.roster).map(([role, players]) => [role, players.length])), `team ${team.name} seats`).toEqual(SHAPE);
  }
  const seated = variant.teams.flatMap((team) => Object.values(team.roster).flat().map((p) => p.uuid));
  expect(variant.benched_players).toHaveLength(1);
  expect(new Set([...seated, ...variant.benched_players.map((p) => p.uuid)]), "every pool registration seated or benched once").toEqual(
    new Set(tagById.keys())
  );

  const saved = await adminApi.call<{ id: number }>("PUT", `/api/v1/balancer/tournaments/${t.id}/balance`, {
    body: { config_json: config.config_json, result_json: variant },
    query: formation,
  });
  expect(await adminApi.get<{ id: number }>(`/api/v1/balancer/tournaments/${t.id}/balance`, formation)).toMatchObject({ id: saved.id });

  const exported = await adminApi.post<{ imported_teams: number; advisories: string[] }>(`/api/v1/balancer/balances/${saved.id}/export`, {});
  expect(exported.imported_teams).toBe(2);
  expect(exported.advisories, "no member skipped or unresolved").toEqual([]);

  const teams = await listTeams(adminApi, t.id);
  expect(teams).toHaveLength(2);
  for (const balanced of variant.teams) {
    const expected = Object.values(balanced.roster).flat().map((p) => tagById.get(p.uuid));
    const team = teams.find((x) => expected.includes(x.players.find((p) => p.user_id === x.captain_id)?.name ?? ""));
    expect(team, `exported team for balanced team ${balanced.name}`).toBeTruthy();
    expect(team!.players.map((p) => p.name).sort()).toEqual([...expected].sort());
  }

  // Rank-only re-export: a corrected rating reaches the exported player, the teams stay.
  const moved = variant.teams[0].roster.support[0];
  moved.assigned_rating += 111;
  const resaved = await adminApi.call<{ id: number }>("PUT", `/api/v1/balancer/tournaments/${t.id}/balance`, {
    body: { config_json: config.config_json, result_json: variant },
    query: formation,
  });
  const ranks = await adminApi.post<{ updated_players: number }>(`/api/v1/balancer/balances/${resaved.id}/export-ranks`, {});
  expect(ranks.updated_players).toBe(1);
  // The gateway cache is invalidated after commit; a ≤1 s tournament-service gap is accepted,
  // a roster still stale after 5 s is the cache-invalidation bug.
  await expect
    .poll(
      async () => (await listTeams(adminApi, t.id)).flatMap((x) => x.players).find((p) => p.name === tagById.get(moved.uuid))?.rank,
      { timeout: 5_000, message: "GET /teams shows the rank export-ranks wrote" }
    )
    .toBe(moved.assigned_rating);
  expect((await listTeams(adminApi, t.id)).map((x) => x.id).sort(), "rank-only export keeps the teams").toEqual(teams.map((x) => x.id).sort());

  // No registered (captain-formed) teams: the registered-teams export imports nothing and leaves the balancer's teams alone.
  const registered = await adminApi.call<{ imported_teams: number; removed_teams: number }>(
    "POST",
    `/api/v1/balancer/tournaments/${t.id}/registered-teams/export`,
    { body: {}, query: formation }
  );
  expect(registered).toMatchObject({ imported_teams: 0, removed_teams: 0 });
  expect((await listTeams(adminApi, t.id)).map((x) => x.id).sort()).toEqual(teams.map((x) => x.id).sort());
});

test("balance job response advertises only the /api/v1 status and result URLs, and both resolve", async ({ adminApi }) => {
  const ws = await createWorkspace(adminApi);
  const t = await createTournament(adminApi, ws.id);
  const { formation } = await formingPool(adminApi, t.id, 10);
  const job = await adminApi.call<CreateJob & Record<string, unknown>>("POST", `/api/v1/balancer/tournaments/${t.id}/balance`, {
    body: {},
    query: formation,
    expectStatus: 202,
  });
  expect(job, "no stream URL: progress is on the realtime topic, the SSE route does not exist").not.toHaveProperty("stream_url");
  expect(job.status_url).toBe(`/api/v1/balancer/jobs/${job.job_id}`);
  expect(job.result_url).toBe(`/api/v1/balancer/jobs/${job.job_id}/result`);
  const done = await poll(
    async () => {
      const s = await adminApi.get<BalancerJob>(job.status_url);
      return s.status === "succeeded" || s.status === "failed" ? s : undefined;
    },
    `balance job ${job.job_id}`,
    120_000
  );
  expect(done.status).toBe("succeeded");
  const result = await adminApi.get<{ variants: unknown[] }>(job.result_url);
  expect(result.variants.length).toBeGreaterThan(0);
});

test("empty pool: the balance job is refused with 422", async ({ adminApi }) => {
  const ws = await createWorkspace(adminApi);
  const t = await createTournament(adminApi, ws.id);
  const { formation } = await formingPool(adminApi, t.id, 0);
  const res = await adminApi.raw("POST", `/api/v1/balancer/tournaments/${t.id}/balance`, { body: {}, query: formation });
  expect(res.status()).toBe(422);
});

test("synchronous balance solves the posted pool, scoped to a writable workspace", async ({ adminApi, makeUser }) => {
  const ws = await createWorkspace(adminApi);
  const roles = ["tank", "damage", "damage", "support", "support"];
  const players = Object.fromEntries(
    Array.from({ length: 10 }, (_, i) => [
      `u${i}`,
      {
        identity: { name: `Sync${i}` },
        stats: {
          classes: {
            [roles[i % 5]]: { isActive: true, rank: 2000 + i * 100, priority: 0 },
            [roles[(i + 3) % 5]]: { isActive: true, rank: 1900 + i * 90, priority: 1 },
          },
        },
      },
    ])
  );
  const body = { player_data: { players }, role_mask: SHAPE, config_overrides: { generation_count: 60 } };
  const result = await adminApi.call<{ variants: { teams: { roster: Record<string, unknown[]> }[] }[] }>("POST", "/api/v1/balancer/balance", {
    body,
    query: { workspace_id: ws.id, discipline: "overwatch" },
  });
  expect(result.variants[0].teams.map((team) => Object.values(team.roster).flat().length)).toEqual([5, 5]);

  const stranger = await makeUser("nosync");
  const denied = await stranger.api.raw("POST", "/api/v1/balancer/balance", { body, query: { workspace_id: ws.id, discipline: "overwatch" } });
  expect(denied.status()).toBe(403);
});

test("workspace balancer config, mix ranker knobs and rebuild", async ({ adminApi, makeUser }) => {
  const ws = await createWorkspace(adminApi);
  const base = `/api/v1/balancer/workspaces/${ws.id}`;
  expect(await adminApi.get(`${base}/config`)).toMatchObject({ workspace_id: ws.id, rank_delta_threshold: null, rank_delta_hide_from_pool: false });
  await adminApi.put(`${base}/config`, { rank_delta_threshold: 300, rank_delta_hide_from_pool: true });
  expect(await adminApi.get(`${base}/config`)).toMatchObject({ rank_delta_threshold: 300, rank_delta_hide_from_pool: true });

  const ranker = await adminApi.get<Record<string, number | string>>(`${base}/ranker`);
  expect(ranker).toMatchObject({ workspace_id: ws.id, hidden_ratings: 0 });
  const knobs = { rating_min: 0, rating_max: 5000, rating_avg: 2500, gravity: 0.4, gate_steepness: 3, sigma_init: 30, variant: "corrected" };
  const bad = await adminApi.raw("PUT", `${base}/ranker`, { body: { ...knobs, rating_avg: 6000 } });
  expect(bad.status(), "rating_avg outside min..max").toBe(422);
  expect(await adminApi.put(`${base}/ranker`, knobs)).toMatchObject(knobs);
  expect(await adminApi.get(`${base}/ranker`)).toMatchObject(knobs);
  expect(await adminApi.post(`${base}/ranker/rebuild`)).toEqual({ matches: 0, hidden_ratings: 0 });

  const stranger = await makeUser("nows");
  expect((await stranger.api.raw("GET", `${base}/config`)).status()).toBe(403);
  expect((await stranger.api.raw("PUT", `${base}/ranker`, { body: knobs })).status()).toBe(403);
});

test("workspace roster: registrations become members; canon and author layers stay apart; OW ranks sit on the ladder", async ({ adminApi, makeUser }) => {
  const ws = await createWorkspace(adminApi);
  type Tier = { number: number; rank_min: number; rank_max: number | null };
  const t = (await createTournament(adminApi, ws.id)) as Tournament & { division_grid_version: { tiers: Tier[] } };
  const { registrationNodeId } = await openRegistration(adminApi, t.id);
  const [first, second] = await seedPlayers(adminApi, t.id, 2, { registrationNodeId });
  const base = `/api/v1/balancer/workspaces/${ws.id}`;
  type Row = { member_id: number; identity: { handle: string } | null; ranks: Record<string, number>; author_ranks: Record<string, number> };
  const find = async (handle: string, query: Record<string, string | number> = {}) => {
    const page = await adminApi.get<{ results: Row[] }>(`${base}/players`, { discipline: "overwatch", query: handle.split("#")[0], ...query });
    const row = page.results.find((r) => r.identity?.handle === handle);
    expect(row, `roster row for ${handle}`).toBeTruthy();
    return row!;
  };
  const a = await find(first.primary_handle!);
  const b = await find(second.primary_handle!);
  expect(a).toMatchObject({ ranks: {}, author_ranks: {} });

  await adminApi.put(`${base}/players/${a.member_id}/ranks`, { discipline: "overwatch", scope: "workspace", ranks: { tank: 3150 } });
  await adminApi.put(`${base}/players/${b.member_id}/ranks`, { discipline: "overwatch", scope: "author", ranks: { support: 2675 } });
  expect(await find(first.primary_handle!)).toMatchObject({ ranks: { tank: 3150 }, author_ranks: {} });
  expect(await find(second.primary_handle!)).toMatchObject({ ranks: {}, author_ranks: { support: 2675 } });

  for (const [body, why] of [
    [{ discipline: "overwatch", scope: "workspace", ranks: { top: 3000 } }, "a LoL role on an OW write"],
    [{ scope: "workspace", ranks: { tank: 3000 } }, "no discipline"],
    [{ discipline: "lol", scope: "workspace", ranks: { top: 3000 } }, "a game the workspace has not enabled"],
  ] as const) {
    expect((await adminApi.raw("PUT", `${base}/players/${a.member_id}/ranks`, { body })).status(), why).toBe(422);
  }

  const admin = await adminApi.get<{ id: number }>("/api/v1/auth/me");
  expect(await adminApi.get(`${base}/players/summary`, { author_user_id: admin.id })).toMatchObject({ author_total: 1 });
  expect((await adminApi.get<{ authors: { user_id: number; count: number }[] }>(`${base}/players/authors`)).authors).toEqual([
    expect.objectContaining({ user_id: admin.id, count: 1 }),
  ]);

  type RankRow = { layer: string; member_id: number; role: string; rank_value: number; division: number | null; context: { kind: string; id?: number } | null };
  const overview = await adminApi.get<{ results: RankRow[] }>(`${base}/ranks`, { discipline: "overwatch", per_page: 100 });
  const rowsOf = (member: number) => overview.results.filter((r) => r.member_id === member).map((r) => `${r.layer}:${r.role}=${r.rank_value}`).sort();
  // effective_mix is per author book: a member nobody has a book on has none.
  expect(rowsOf(a.member_id)).toEqual(["canon:tank=3150", "effective_tournament:tank=3150"]);
  expect(rowsOf(b.member_id)).toEqual(expect.arrayContaining(["author:support=2675", "effective_mix:support=2675"]));
  expect(rowsOf(b.member_id), "an author's book never becomes canon").not.toContain("canon:support=2675");

  // Rank mapping is gone: an OW value is placed on the grid by its own tier bounds.
  const canon = overview.results.find((r) => r.member_id === a.member_id && r.layer === "canon")!;
  const tier = t.division_grid_version.tiers.find((x) => 3150 >= x.rank_min && (x.rank_max === null || 3150 <= x.rank_max));
  expect(canon.division).toBe(tier?.number);

  const registration = await adminApi.get<{ results: RankRow[] }>(`${base}/ranks`, { discipline: "overwatch", layer: "registration" });
  expect(registration.results.filter((r) => r.member_id === a.member_id)[0]).toMatchObject({
    rank_value: first.roles[0].rank_value,
    context: expect.objectContaining({ kind: "tournament", id: t.id }),
  });

  const stranger = await makeUser("noroster");
  expect((await stranger.api.raw("GET", `${base}/players`, { query: { discipline: "overwatch" } })).status()).toBe(403);
  expect((await stranger.api.raw("GET", `${base}/ranks`, { query: { discipline: "overwatch" } })).status()).toBe(403);
});
