import type { Api } from "../support/api";
import { expect, test } from "../support/fixtures";
import {
  balanceAndExport,
  battleTag,
  completeStages,
  createStage,
  startStage,
  listEncounters,
  OW_FORM,
  openRegistration,
  openWindows,
  playerIdOf,
  rankRegistration,
  recalcStandings,
  registerSelf,
  seedBracket,
  seedPlayers,
  setResult,
  type Encounter,
  type Registration,
  type Stage,
  type StageType,
  type Team,
} from "../support/flows";
import { createTournament, createWorkspace, flowNodes, nodeOf, setArchived, transitionNode, type Tournament } from "../support/seed";
import type { TestUser } from "../support/users";

type Readiness = {
  status: string;
  schedule_configured: boolean;
  registration_form_configured: boolean;
  registrations_pending: number;
  registrations_approved: number;
  registrations_checked_in: number;
  registrations_ranked: number;
  pool_ready: number;
  balance_saved: boolean;
  balance_exported_at: string | null;
  stages_total: number;
  stage_slots_filled: boolean;
  bracket_generated: boolean;
  duel_encounters_total: number;
  results_pending_confirmation: number;
};

type ApiError = { code: string; detail: string; fields?: { code: string }[] };

/** A refused node move answers 409 with its machine code. */
async function expectNodeMoveRefused(api: Api, nodeId: number, status: string, code: string) {
  const res = await api.raw("POST", `/api/v1/admin/flow-nodes/${nodeId}/transition`, { body: { status } });
  const body = (await res.json()) as ApiError;
  expect(res.status(), `→ ${status} must be refused: ${JSON.stringify(body)}`).toBe(409);
  expect(body.fields?.map((f) => f.code), `→ ${status} error code`).toContain(code);
}

// 4 teams × (1 tank, 2 damage, 2 support). Index 12 signs up as damage and edits to support.
const POOL_ROLES = [
  ...Array<string>(4).fill("tank"),
  ...Array<string>(8).fill("damage"),
  ...Array<string>(8).fill("support"),
];
const EDITOR = 12;

test("overwatch lifecycle: announcement → archived through the API", async ({ adminApi, anonApi, makeUser }) => {
  test.setTimeout(600_000);
  const readiness = () => adminApi.get<Readiness>(`/api/v1/admin/tournaments/${tid}/readiness`);
  const ws = await createWorkspace(adminApi);
  const created = await createTournament(adminApi, ws.id);
  const tid = created.id;

  await test.step("announcement: empty readiness, guarded node moves", async () => {
    expect(created.status).toBe("announcement");
    const r = await readiness();
    expect(r).toMatchObject({
      status: "announcement",
      schedule_configured: false,
      registration_form_configured: false,
      stages_total: 0,
      bracket_generated: false,
    });
    const registration = await nodeOf(adminApi, tid, "registration");
    const formation = await nodeOf(adminApi, tid, "formation");
    expect(registration.status).toBe("draft");
    await expectNodeMoveRefused(adminApi, registration.id, "check_in", "invalid_node_transition");
    await expectNodeMoveRefused(adminApi, registration.id, "closed", "invalid_node_transition");
    await expectNodeMoveRefused(adminApi, formation.id, "completed", "invalid_node_transition");
    await expectNodeMoveRefused(adminApi, registration.id, "open", "registration_form_missing");
    const still = await adminApi.get<Tournament>(`/api/v1/admin/tournaments/${tid}`);
    expect(still.status, "refused moves left the status alone").toBe("announcement");
  });

  let versionId = 0;
  let registrationNodeId = 0;
  await test.step("form + registration node open + schedule", async () => {
    await adminApi.put(`/api/v1/admin/balancer/tournaments/${tid}/registration-form`, { form_schema: OW_FORM });
    expect((await readiness()).registration_form_configured).toBe(true);
    expect((await readiness()).schedule_configured).toBe(false);

    // Saves the form again, writes the sign-up and check-in windows and moves the node draft → open.
    ({ versionId, registrationNodeId } = await openRegistration(adminApi, tid));
    const after = await readiness();
    expect(after.schedule_configured).toBe(true);
    expect(after.status, "a lifecycle node left draft: the tournament is live").toBe("live");

    const node = (await flowNodes(anonApi, tid)).find((candidate) => candidate.id === registrationNodeId);
    expect(node?.status, "the public page announces the open intake").toBe("open");
    expect(node?.schedule.map((entry) => entry.phase).sort()).toEqual(openWindows().map((entry) => entry.phase).sort());
  });

  const pool: TestUser[] = [];
  const regs = new Map<number, Registration>();
  let withdrawer: TestUser;
  let rejected: TestUser;
  await test.step("players register, edit, withdraw", async () => {
    const anon = await anonApi.raw("POST", `/api/v1/tournaments/${tid}/registration`, {
      body: { form_version_id: versionId, answers: { identity_battlenet: ["Anon#1234"], roles: [{ role: "tank", is_primary: true }] } },
    });
    expect(anon.status(), "anonymous sign-up").toBe(401);

    for (const [i, role] of POOL_ROLES.entries()) {
      const user = await makeUser("lc");
      pool.push(user);
      const reg = await registerSelf(user, tid, registrationNodeId, versionId, { roles: [i === EDITOR ? "damage" : role] });
      expect(reg.status).toBe("pending");
      regs.set(i, reg);
    }
    withdrawer = await makeUser("lcw");
    rejected = await makeUser("lcr");
    const withdrawnReg = await registerSelf(withdrawer, tid, registrationNodeId, versionId, { roles: ["tank"] });
    const rejectedReg = await registerSelf(rejected, tid, registrationNodeId, versionId, { roles: ["damage"] });

    const dup = await pool[0].api.raw("POST", `/api/v1/tournaments/${tid}/registration`, {
      body: { form_version_id: versionId, answers: { identity_battlenet: [battleTag("dup")], roles: [{ role: "tank", is_primary: true }] } },
    });
    expect(dup.status(), "second sign-up by the same player").toBe(409);

    // Edit while pending: damage → support, stream POV on.
    const editor = pool[EDITOR];
    const mine = await editor.api.get<Registration>(`/api/v1/tournaments/${tid}/registration/me`);
    expect(mine.can_edit, "a pending entry on an editable form can be edited").toBe(true);
    // A read → modify → write round trip: GET echoes server-managed keys (`reserve`) the form never asked, and PATCH takes them back unchanged.
    const edited = await editor.api.patch<Registration>(`/api/v1/tournaments/${tid}/registration/me`, {
      form_version_id: versionId,
      answers: { ...mine.answers, roles: [{ role: "support", is_primary: true }], stream_pov: true },
    });
    expect(edited.roles.map((r) => r.role.role)).toEqual(["support"]);
    expect(edited.answers.stream_pov).toBe(true);
    expect((await editor.api.get<Registration>(`/api/v1/tournaments/${tid}/registration/me`)).roles[0].role.role).toBe("support");
    regs.set(EDITOR, edited);

    const gone = await withdrawer.api.delete<{ status: string }>(`/api/v1/tournaments/${tid}/registration/me`);
    expect(gone.status).toBe("withdrawn");
    const mineGone = await withdrawer.api.get<Registration | null>(`/api/v1/tournaments/${tid}/registration/me`);
    expect(mineGone?.status ?? "withdrawn", "withdrawn entry reads back as withdrawn or gone").toBe("withdrawn");

    const r = await readiness();
    expect(r.registrations_pending, "20 pool + 1 to reject; the withdrawn one is not pending").toBe(21);
    expect(r.registrations_approved).toBe(0);

    // Organizer review: one approve, one reject, bulk-approve the rest.
    const approvedOne = await adminApi.patch<Registration>(`/api/v1/admin/balancer/registrations/${regs.get(0)!.id}/approve`);
    expect(approvedOne.status).toBe("approved");
    const rejectedOne = await adminApi.patch<Registration>(`/api/v1/admin/balancer/registrations/${rejectedReg.id}/reject`);
    expect(rejectedOne.status).toBe("rejected");
    const bulk = await adminApi.post<{ approved: number; skipped: number }>(
      `/api/v1/admin/balancer/tournaments/${tid}/registrations/bulk-approve`,
      { registration_ids: [...regs.values()].map((x) => x.id) }
    );
    expect(bulk.approved + bulk.skipped).toBe(20);
    expect(bulk.approved, "already-approved entry is skipped").toBe(19);

    const after = await readiness();
    expect(after.registrations_approved).toBe(20);
    expect(after.registrations_pending).toBe(0);

    // The public list shows every entry with its status badge (withdrawn/rejected included).
    const list = await anonApi.get<{ registrations: Registration[] }>(`/api/v1/tournaments/${tid}/registration/list`);
    const statusOf = new Map(list.registrations.map((x) => [x.id, x.status]));
    for (const reg of regs.values()) expect(statusOf.get(reg.id), `public list: ${reg.id}`).toBe("approved");
    expect(statusOf.get(rejectedReg.id)).toBe("rejected");
    expect(statusOf.get(withdrawnReg.id)).toBe("withdrawn");
  });

  await test.step("ranks + balancer pool", async () => {
    for (const [i, reg] of regs) {
      const role = reg.roles[0].role;
      await rankRegistration(adminApi, reg.id, [{ role, rank: 1800 + i * 60 }]);
    }
    await adminApi.post(`/api/v1/admin/balancer/tournaments/${tid}/registrations/bulk-add-to-balancer`, {
      registration_ids: [...regs.values()].map((x) => x.id),
    });
    const r = await readiness();
    expect(r.registrations_ranked).toBe(20);
    expect(r.pool_ready).toBe(20);
  });

  await test.step("check-in", async () => {
    const early = await pool[1].api.raw("POST", `/api/v1/tournaments/${tid}/registration/me/check-in`);
    expect(early.status(), "check-in before CHECK_IN status").toBe(409);

    await transitionNode(adminApi, registrationNodeId, "check_in");
    for (const user of pool) {
      const me = await user.api.post<Registration>(`/api/v1/tournaments/${tid}/registration/me/check-in`);
      expect(me.checked_in, `${user.username} checked in`).toBe(true);
    }
    const refused = await rejected.api.raw("POST", `/api/v1/tournaments/${tid}/registration/me/check-in`);
    expect(refused.ok(), `rejected player check-in answered ${refused.status()}`).toBe(false);
    const late = await pool[2].api.raw("DELETE", `/api/v1/tournaments/${tid}/registration/me`);
    expect(late.status(), "withdraw after check-in").toBe(409);
    expect((await readiness()).registrations_checked_in).toBe(20);
    // The formation's input must be final before it can start.
    await transitionNode(adminApi, registrationNodeId, "closed");
  });

  let teams: Team[] = [];
  await test.step("balancer: config, async balance, save + export", async () => {
    await adminApi.put(`/api/v1/balancer/tournaments/${tid}/config`, { config_json: { use_captains: true, generation_count: 150 } });
    const cfg = await adminApi.get<{ config_json: Record<string, unknown> }>(`/api/v1/balancer/tournaments/${tid}/config`);
    expect(cfg.config_json).toMatchObject({ use_captains: true, generation_count: 150 });

    const formation = await nodeOf(adminApi, tid, "formation");
    const out = await balanceAndExport(adminApi, tid, formation.id);
    for (const team of out.variant.teams) {
      const captains = Object.values(team.roster).flat().filter((p) => p.is_captain);
      expect(captains, `${team.name}: one captain with use_captains`).toHaveLength(1);
    }
    teams = out.teams;
    expect(teams).toHaveLength(4);
    const playerIds = new Map<number, TestUser>();
    for (const user of pool) playerIds.set(await playerIdOf(user), user);
    const placed = teams.flatMap((t) => t.players.map((p) => p.user_id));
    expect(new Set(placed).size, "every pool player on exactly one team").toBe(20);
    for (const id of placed) expect(playerIds.has(id), `player ${id} came from the pool`).toBe(true);
    for (const team of teams) {
      expect(team.players.map((p) => p.role?.role).sort()).toEqual(["damage", "damage", "support", "support", "tank"]);
      expect(team.players.map((p) => p.user_id), `${team.name}: captain is on the roster`).toContain(team.captain_id);
    }
    const r = await readiness();
    expect(r.balance_saved).toBe(true);
    expect(r.balance_exported_at).toBeTruthy();
  });

  let groups: Stage;
  let encounters: Encounter[] = [];
  await test.step("group stage seeded; starting its node generates it", async () => {
    groups = await createStage(adminApi, tid, teams.map((t) => t.id), { stageType: "round_robin", name: "Groups", bestOf: 3 });
    expect(groups.items[0].inputs).toHaveLength(4);
    let r = await readiness();
    expect(r.stages_total).toBe(1);
    expect(r.stage_slots_filled).toBe(true);
    expect(r.bracket_generated).toBe(false);

    await startStage(adminApi, groups);
    // Starting the node generates the stage's first matches.
    await expect
      .poll(async () => (encounters = await listEncounters(anonApi, tid, groups.id)).length, {
        message: "LIVE autostarts the seeded round-robin stage (6 encounters, no manual generate)",
        timeout: 30_000,
      })
      .toBe(6);
    const stages = await anonApi.get<Stage[]>(`/api/v1/tournaments/${tid}/stages`);
    expect(stages.find((s) => s.id === groups.id)).toMatchObject({ status: "live", is_published: true });
    r = await readiness();
    expect(r.bracket_generated).toBe(true);
    expect(r.duel_encounters_total).toBe(6);
  });

  const strength = (teamId: number | null) => teams.findIndex((t) => t.id === teamId);
  await test.step("results: captains report one series, organizer enters the rest", async () => {
    const byPlayer = new Map<number, TestUser>();
    for (const user of pool) byPlayer.set(await playerIdOf(user), user);

    // Lower index in `teams` always wins 2:1, so the table is teams[0..3].
    const [first, ...rest] = encounters;
    const seats = [...first.teams].sort((a, b) => a.slot - b.slot);
    const report = {
      basis_version: first.result_version,
      games_played: 3,
      closeness: 6,
      results: seats.map((s) => ({ encounter_team_id: s.id, score: strength(s.team_id) === Math.min(...seats.map((x) => strength(x.team_id))) ? 2 : 1 })),
    };
    const captains = seats.map((s) => byPlayer.get(teams.find((t) => t.id === s.team_id)!.captain_id!)!);
    expect(captains.every(Boolean), "both captains are pool users").toBe(true);
    const role = await captains[0].api.get<{ encounter_team_id: number }>(`/api/v1/encounters/${first.id}/my-role`);
    expect(role.encounter_team_id).toBe(seats[0].id);

    const one = await captains[0].api.post<{ result_status: string }>(`/api/v1/encounters/${first.id}/report`, report);
    expect(one.result_status).toBe("pending_confirmation");
    expect((await readiness()).results_pending_confirmation).toBe(1);
    const two = await captains[1].api.post<{ result_status: string; status: string }>(`/api/v1/encounters/${first.id}/report`, report);
    expect(two).toMatchObject({ result_status: "confirmed", status: "completed" });
    expect((await readiness()).results_pending_confirmation).toBe(0);

    for (const enc of rest) {
      const scores = [...enc.teams].sort((a, b) => a.slot - b.slot).map((s, _i, all) =>
        strength(s.team_id) === Math.min(...all.map((x) => strength(x.team_id))) ? 2 : 1
      );
      const res = await setResult(adminApi, enc, scores);
      expect(res).toMatchObject({ status: "completed", result_status: "confirmed" });
    }
    const pub = await anonApi.get<Encounter>(`/api/v1/encounters/${first.id}`);
    expect(pub.teams.map((s) => s.score).sort()).toEqual([1, 2]);
  });

  await test.step("standings: recalc, order and points", async () => {
    const rows = (await recalcStandings(adminApi, tid)).filter((r) => r.stage_id === groups.id);
    expect(rows.map((r) => r.team_id), "group table order").toEqual(teams.map((t) => t.id));
    expect(rows.map((r) => r.points)).toEqual([3, 2, 1, 0]);
    expect(rows.map((r) => [r.win, r.lose])).toEqual([
      [3, 0],
      [2, 1],
      [1, 2],
      [0, 3],
    ]);
    expect(rows.map((r) => r.position)).toEqual([1, 2, 3, 4]);
  });

  await test.step("playoffs: final between the top two", async () => {
    const final = await createStage(adminApi, tid, [teams[0].id, teams[1].id], {
      stageType: "single_elimination",
      name: "Final",
      order: 1,
    });
    await startStage(adminApi, final);
    const [match] = await listEncounters(anonApi, tid, final.id);
    expect(match.teams.map((s) => s.team_id).sort()).toEqual([teams[0].id, teams[1].id].sort());
    // The group runner-up takes the title.
    await setResult(adminApi, match, [...match.teams].sort((a, b) => a.slot - b.slot).map((s) => (s.team_id === teams[1].id ? 2 : 0)));
    const rows = (await recalcStandings(adminApi, tid)).filter((r) => r.stage_id === final.id);
    expect(rows.find((r) => r.position === 1)?.team_id, "final winner first").toBe(teams[1].id);
  });

  await test.step("every stage completed → tournament completed → archived", async () => {
    await completeStages(adminApi, tid);
    const done = await adminApi.get<Tournament & { is_finished: boolean }>(`/api/v1/tournaments/${tid}`);
    expect(done).toMatchObject({ status: "completed", is_finished: true });
    const registration = (await flowNodes(anonApi, tid)).find((node) => node.id === registrationNodeId);
    expect(registration?.status, "a finished tournament takes no sign-ups").toBe("closed");
    await expectNodeMoveRefused(adminApi, registrationNodeId, "open", "downstream_started");
    await setArchived(adminApi, tid, true);
    const pub = await anonApi.get<Tournament & { is_finished: boolean }>(`/api/v1/tournaments/${tid}`);
    expect(pub).toMatchObject({ status: "archived", is_finished: true });
    expect((await readiness()).status).toBe("archived");
  });
});

for (const stageType of ["round_robin", "single_elimination", "double_elimination", "swiss", "ffa_league"] as StageType[]) {
  test(`seedBracket generates a published ${stageType} stage on a LIVE tournament`, async ({ adminApi, anonApi }) => {
    const seed = await seedBracket(adminApi, { stageType, teams: 4 });
    expect(seed.tournament.status).toBe("live");
    expect(seed.stage.is_published).toBe(true);
    const teamIds = seed.teams.map((t) => t.id);
    const seated = seed.encounters.flatMap((e) => e.teams.map((s) => s.team_id)).filter((id) => id !== null);
    expect(seated.length).toBeGreaterThan(0);
    for (const id of seated) expect(teamIds).toContain(id);
    const pub = await anonApi.get<Stage[]>(`/api/v1/tournaments/${seed.tournament.id}/stages`);
    expect(pub.map((s) => s.id)).toContain(seed.stage.id);
  });
}

test("seedPlayers + balanceAndExport build teams from the pool", async ({ adminApi }) => {
  const ws = await createWorkspace(adminApi);
  const t = await createTournament(adminApi, ws.id);
  const { registrationNodeId } = await openRegistration(adminApi, t.id);
  await seedPlayers(adminApi, t.id, 10, { registrationNodeId });
  await transitionNode(adminApi, registrationNodeId, "closed");
  const formation = await nodeOf(adminApi, t.id, "formation");
  const out = await balanceAndExport(adminApi, t.id, formation.id);
  expect(out.teams).toHaveLength(2);
  for (const team of out.teams) expect(team.players).toHaveLength(5);
});
