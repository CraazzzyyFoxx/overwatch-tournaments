import { poll } from "../support/api";
import { expect, test } from "../support/fixtures";
import { battleTag, generateStage, listEncounters, openRegistration, rankRegistration, registerSelf, type FormSchema, type Registration, type Stage, type TournamentJob } from "../support/flows";
import { reportSeries, series, setPoints } from "../support/results";
import { createTournament, createWorkspace, setStatus } from "../support/seed";
import { draftBoard, type DraftBoard, type DraftSession } from "../support/team-formation";
import type { TestUser } from "../support/users";

// Individual Swiss + draft playoff, end to end over the gateway: single-role
// registration → pool check on start → rounds with fresh teams (no tournament
// team, snapshot captains) → personal standings, pins → qualification lock
// (LIVE → DRAFT) → draft seeded with exactly the qualifiers and 2 captains.

const ROLES = [...Array<string>(4).fill("tank"), ...Array<string>(8).fill("damage"), ...Array<string>(8).fill("support")];
const SHAPE: Record<string, number> = { tank: 1, damage: 2, support: 2 };
const PLAYOFF_TEAMS = 2;
const ROUNDS = 2;

const SWISS_FORM: FormSchema = {
  schema_version: 1,
  sections: [
    {
      key: "main",
      title: "Player",
      fields: [
        { key: "identity_battlenet", kind: "builtin", required: true, editable: true },
        { key: "roles", kind: "builtin", required: true, editable: true, params: { max_roles: 1, flex_allowed: false } },
      ],
    },
  ],
};

type Standing = {
  stage_id: number;
  workspace_member_id: number;
  registration_id: number | null;
  display_name: string;
  role: string;
  rank: number;
  position: number | null;
  points: number;
  wins: number;
  draws: number;
  losses: number;
  matches_played: number;
  maps_won: number;
  maps_lost: number;
  map_diff: number;
  is_pinned: boolean;
  is_qualified: boolean;
  is_captain: boolean;
};
type SeatMember = { workspace_member_id: number; display_name: string; role: string | null; rank: number | null; is_captain: boolean };
type RoundSeat = { participation_id: number; slot: number; name: string; score: number; members: SeatMember[] };
type Round = { round: number; encounters: { encounter_id: number; best_of: number; status: string; result_status: string; seats: RoundSeat[] }[] };
type Lock = { captains: Standing[]; qualified: Standing[] };

test("individual swiss: single-role pool → rounds by captains → personal table → pins → lock → draft", async ({ adminApi, anonApi, makeUser }) => {
  test.setTimeout(600_000);

  const ws = await createWorkspace(adminApi);
  const t = await createTournament(adminApi, ws.id, { team_formation: "draft" });
  const tid = t.id;
  const adminRegs = `/api/v1/admin/balancer/tournaments/${tid}/registrations`;
  const adminReg = (id: number) => `/api/v1/admin/balancer/registrations/${id}`;

  let version = 0;
  await test.step("1 — draft tournament, registration form with max_roles 1", async () => {
    version = await openRegistration(adminApi, tid, { form: SWISS_FORM });
  });

  await test.step("2 — two roles are refused with roles.too_many_roles", async () => {
    const greedy = await makeUser("two");
    const res = await greedy.api.raw("POST", `/api/v1/tournaments/${tid}/registration`, {
      body: {
        form_version_id: version,
        answers: {
          identity_battlenet: [battleTag(greedy.username)],
          roles: [
            { role: "tank", is_primary: true },
            { role: "damage", is_primary: false },
          ],
        },
      },
    });
    const body = await res.text();
    expect(res.status(), body).toBeGreaterThanOrEqual(400);
    expect(res.status(), body).toBeLessThan(500);
    expect(body).toContain("roles.too_many_roles");
  });

  const users: TestUser[] = [];
  const regs: Registration[] = [];
  const userOfReg = new Map<number, TestUser>();
  await test.step("3 — 20 one-role players register, are approved and ranked; tournament goes LIVE", async () => {
    for (const role of ROLES) users.push(await makeUser("sw"));
    const made = await Promise.all(users.map((user, i) => registerSelf(user, tid, version, { roles: [ROLES[i]] })));
    regs.push(...made);
    made.forEach((reg, i) => userOfReg.set(reg.id, users[i]));
    expect(made.map((r) => r.roles.length)).toEqual(made.map(() => 1));

    const bulk = await adminApi.post<{ approved: number }>(`${adminRegs}/bulk-approve`, { registration_ids: regs.map((r) => r.id) });
    expect(bulk.approved).toBe(20);
    // Distinct ranks (1800 + 60·i): the captain of a round team is its highest-ranked member.
    for (const [i, reg] of regs.entries()) await rankRegistration(adminApi, reg.id, [{ role: reg.roles[0].role, rank: 1800 + i * 60 }]);
    await adminApi.post(`${adminRegs}/bulk-add-to-balancer`, { registration_ids: regs.map((r) => r.id) });

    await setStatus(adminApi, tid, "check_in");
    await setStatus(adminApi, tid, "live");
    expect((await anonApi.get<{ status: string }>(`/api/v1/tournaments/${tid}`)).status).toBe("live");
    await setPoints(adminApi, tid, 3, 1, 0);
  });

  let stage: Stage;
  await test.step("4a — stage individual_swiss is created with its settings", async () => {
    stage = await adminApi.post<Stage & { pairing_mode: string; playoff_team_count: number; max_rounds: number }>(
      `/api/v1/admin/stages/tournament/${tid}`,
      { name: "Swiss", stage_type: "individual_swiss", best_of: { default: 3 }, order: 0, max_rounds: ROUNDS, playoff_team_count: PLAYOFF_TEAMS },
      201
    );
    expect(stage).toMatchObject({ stage_type: "individual_swiss", pairing_mode: "score", playoff_team_count: PLAYOFF_TEAMS, max_rounds: ROUNDS });
  });

  const roundsUrl = () => `/api/v1/tournaments/${tid}/stages/${stage.id}/individual-rounds`;
  const readRounds = () => anonApi.get<Round[]>(roundsUrl());
  const readStandings = () => anonApi.get<Standing[]>(`/api/v1/tournaments/${tid}/player-standings`);

  await test.step("5 — an odd pool is refused by the start with role_count_mismatch and writes nothing", async () => {
    const victim = regs[regs.length - 1];
    await adminApi.post(`${adminRegs}/bulk-set-balancer-status`, { registration_ids: [victim.id], balancer_status: "excluded" });
    const job = await adminApi.post<TournamentJob>(`/api/v1/admin/stages/${stage.id}/activate-and-generate`, undefined, 202);
    const done = await poll(
      async () => {
        const j = await adminApi.get<TournamentJob>(`/api/v1/admin/tournament-jobs/${job.id}`);
        return j.status === "pending" || j.status === "running" ? undefined : j;
      },
      `start job ${job.id}`
    );
    expect(done.status, JSON.stringify(done)).toBe("failed");
    expect(JSON.stringify(done), "the refusal names the pool problem").toContain("role_count_mismatch");
    expect(await readRounds(), "a refused start writes no round").toEqual([]);
    expect(await readStandings(), "a refused start writes no table").toEqual([]);
    expect((await adminApi.post<Registration>(`${adminReg(victim.id)}/include`)).balancer_status).toBe("ready");
  });

  const userOfMember = new Map<number, TestUser>();
  const regOfMember = new Map<number, number>();
  await test.step("6 — activate and generate: round 1 has 2 encounters of rosterless seats, one captain each", async () => {
    await generateStage(adminApi, stage.id);

    const table = await readStandings();
    expect(table).toHaveLength(20);
    for (const row of table) {
      expect(row.registration_id, `${row.display_name} carries its registration`).not.toBeNull();
      userOfMember.set(row.workspace_member_id, userOfReg.get(row.registration_id!)!);
      regOfMember.set(row.workspace_member_id, row.registration_id!);
    }

    const rounds = await readRounds();
    expect(rounds.map((r) => r.round)).toEqual([1]);
    expect(rounds[0].encounters).toHaveLength(2);
    for (const enc of rounds[0].encounters) {
      expect(enc.seats).toHaveLength(2);
      expect(enc.best_of).toBe(3);
      for (const seat of enc.seats) {
        expect(seat.members, `${seat.name}: 5 members`).toHaveLength(5);
        expect(seat.members.map((m) => m.role).sort(), `${seat.name}: roster shape`).toEqual(["damage", "damage", "support", "support", "tank"]);
        const captains = seat.members.filter((m) => m.is_captain);
        expect(captains, `${seat.name}: exactly one captain`).toHaveLength(1);
        expect(captains[0].rank, "the captain is the highest rank of the team").toBe(Math.max(...seat.members.map((m) => m.rank ?? 0)));
        expect(seat.name).toBe(`Команда ${captains[0].display_name}`);
      }
    }

    const encounters = await listEncounters(anonApi, tid, stage.id);
    expect(encounters).toHaveLength(2);
    for (const enc of encounters) for (const seat of enc.teams) expect(seat.team_id ?? null, "a round seat has no tournament team (public reads omit nulls)").toBeNull();
    const stages = await anonApi.get<Stage[]>(`/api/v1/tournaments/${tid}/stages`);
    expect(stages.find((s) => s.id === stage.id)).toMatchObject({ is_active: true, is_published: true });
  });

  const captainOf = (seat: RoundSeat) => userOfMember.get(seat.members.find((m) => m.is_captain)!.workspace_member_id)!;

  /** Both snapshot captains file the same series; the first seat wins `won`:`lost`. */
  const playRound = async (round: Round, won: number, lost: number) => {
    for (const enc of round.encounters) {
      const [first, second] = [...enc.seats].sort((a, b) => a.slot - b.slot);
      const body = series(first.participation_id, second.participation_id, won, lost);
      const pending = await reportSeries(captainOf(first), enc.encounter_id, body);
      expect(pending.result_status, "one report waits for the opponent captain").toBe("pending_confirmation");
      const agreed = await reportSeries(captainOf(second), enc.encounter_id, series(first.participation_id, second.participation_id, won, lost, { closeness: 9 }));
      expect(agreed).toMatchObject({ result_status: "confirmed", status: "completed" });
    }
  };

  await test.step("7a — a non-captain teammate cannot report; the captains agree on round 1", async () => {
    const [round1] = await readRounds();
    const enc = round1.encounters[0];
    const [first, second] = [...enc.seats].sort((a, b) => a.slot - b.slot);
    const teammate = first.members.find((m) => !m.is_captain)!;
    const refused = await userOfMember.get(teammate.workspace_member_id)!.api.raw("POST", `/api/v1/encounters/${enc.encounter_id}/report`, {
      body: series(first.participation_id, second.participation_id, 2, 0),
    });
    expect(refused.status(), "a non-captain teammate reports nothing").toBe(403);
    const outsider = round1.encounters[1].seats[0].members.find((m) => m.is_captain)!;
    const foreign = await userOfMember.get(outsider.workspace_member_id)!.api.raw("POST", `/api/v1/encounters/${enc.encounter_id}/report`, {
      body: series(first.participation_id, second.participation_id, 2, 0),
    });
    expect(foreign.status(), "a captain of another encounter reports nothing here").toBe(403);

    await playRound(round1, 2, 0);
  });

  await test.step("7b — round 2 is generated by the standings job; its captains report; the stage completes", async () => {
    const round2 = await poll(async () => (await readRounds()).find((r) => r.round === 2), "round 2 to appear");
    expect(round2.encounters).toHaveLength(2);
    for (const enc of round2.encounters) for (const seat of enc.seats) expect(seat.members).toHaveLength(5);
    await playRound(round2, 2, 1);

    await poll(async () => (await anonApi.get<Stage[]>(`/api/v1/tournaments/${tid}/stages`)).find((s) => s.id === stage.id)?.is_completed, "stage completion");
    expect((await readRounds()).map((r) => r.round), "no round beyond max_rounds").toEqual([1, 2]);
  });

  const byRole = (rows: Standing[], role: string) => rows.filter((r) => r.role === role).sort((a, b) => a.position! - b.position!);

  await test.step("7c — personal standings: positions per role, map_diff, qualification cut, captains", async () => {
    const rows = await poll(async () => {
      const table = await readStandings();
      return table.every((r) => r.matches_played === ROUNDS) ? table : undefined;
    }, "the table to count both rounds");
    expect(rows).toHaveLength(20);
    expect(rows.reduce((sum, r) => sum + r.points, 0), "4 encounters × 5 winners × 3 points").toBe(60);
    for (const r of rows) {
      expect(r.map_diff, `${r.display_name}: map_diff`).toBe(r.maps_won - r.maps_lost);
      expect(r.wins + r.draws + r.losses).toBe(ROUNDS);
    }
    for (const [role, shape] of Object.entries(SHAPE)) {
      const list = byRole(rows, role);
      expect(list.map((r) => r.position), `${role}: positions`).toEqual(list.map((_, i) => i + 1));
      for (let i = 1; i < list.length; i++) {
        const [a, b] = [list[i - 1], list[i]];
        expect(a.points > b.points || (a.points === b.points && a.map_diff >= b.map_diff), `${role}: ${a.position} before ${b.position} by points, then map_diff`).toBe(true);
      }
      expect(list.filter((r) => r.is_qualified), `${role}: qualified`).toHaveLength(PLAYOFF_TEAMS * shape);
      expect(list.slice(0, PLAYOFF_TEAMS * shape).every((r) => r.is_qualified), `${role}: the cut is the top of the role`).toBe(true);
    }
    const captains = rows.filter((r) => r.is_captain);
    expect(captains, "K captains").toHaveLength(PLAYOFF_TEAMS);
    expect(captains.every((r) => r.is_qualified), "captains are qualifiers").toBe(true);
    const bestQualifiedRank = Math.max(...rows.filter((r) => r.is_qualified).map((r) => r.rank));
    expect(Math.max(...captains.map((r) => r.rank)), "the top-ranked qualifier captains").toBe(bestQualifiedRank);
  });

  let pinned: Standing;
  await test.step("8 — a pin moves a player to the top of their role", async () => {
    const tanks = byRole(await readStandings(), "tank");
    pinned = tanks[tanks.length - 1];
    expect(pinned.is_qualified, "the last tank starts below the cut").toBe(false);
    const put = await adminApi.put<{ pins: { workspace_member_id: number; position: number }[] }>(
      `/api/v1/admin/tournaments/${tid}/stages/${stage.id}/player-standing-pins`,
      { pins: [{ workspace_member_id: pinned.workspace_member_id, position: 1 }] }
    );
    expect(put.pins).toEqual([{ workspace_member_id: pinned.workspace_member_id, position: 1 }]);

    const row = await poll(async () => {
      const r = (await readStandings()).find((x) => x.workspace_member_id === pinned.workspace_member_id);
      return r?.is_pinned && r.position === 1 ? r : undefined;
    }, "the pin to reach the table");
    expect(row.is_qualified, "the pinned tank is inside the cut").toBe(true);
    const after = await readStandings();
    expect(after.filter((r) => r.is_pinned)).toHaveLength(1);
    expect(byRole(after, "tank").filter((r) => r.is_qualified)).toHaveLength(PLAYOFF_TEAMS * SHAPE.tank);
  });

  let lock: Lock;
  await test.step("9 — lock qualification: tournament → draft, non-qualified excluded, second lock refused", async () => {
    const lockUrl = `/api/v1/admin/tournaments/${tid}/stages/${stage.id}/lock-qualification`;
    lock = await adminApi.post<Lock>(lockUrl);
    expect(lock.qualified).toHaveLength(10);
    expect(lock.captains).toHaveLength(PLAYOFF_TEAMS);
    for (const [role, shape] of Object.entries(SHAPE)) expect(lock.qualified.filter((r) => r.role === role), role).toHaveLength(PLAYOFF_TEAMS * shape);
    expect(lock.qualified.map((r) => r.workspace_member_id), "the pin is in the frozen list").toContain(pinned.workspace_member_id);

    expect((await anonApi.get<{ status: string }>(`/api/v1/tournaments/${tid}`)).status).toBe("draft");
    const qualified = new Set(lock.qualified.map((r) => r.registration_id));
    const rows = await adminApi.get<Registration[]>(adminRegs);
    expect(rows.filter((r) => qualified.has(r.id)).every((r) => r.balancer_status !== "excluded"), "qualifiers stay in the pool").toBe(true);
    const out = rows.filter((r) => !qualified.has(r.id));
    expect(out).toHaveLength(10);
    expect(out.every((r) => r.balancer_status === "excluded"), "the rest is excluded").toBe(true);

    const again = await adminApi.raw("POST", lockUrl);
    expect(again.status(), "a second lock").toBe(409);
    const pinsAfter = await adminApi.raw("PUT", `/api/v1/admin/tournaments/${tid}/stages/${stage.id}/player-standing-pins`, { body: { pins: [] } });
    expect(pinsAfter.status(), "the list is frozen at draft").toBe(409);
  });

  await test.step("10 — draft seeded with the 2 captains (weakest first) and exactly the 10 qualifiers", async () => {
    const sessions = `/api/v1/balancer/draft/tournaments/${tid}/sessions`;
    const created = await adminApi.post<DraftSession>(sessions, { pool_source: "manual", pick_time_seconds: 300 });
    const captainRegs = [...lock.captains].sort((a, b) => a.rank - b.rank).map((c) => ({ registration_id: c.registration_id! }));
    await adminApi.post(`${sessions}/${created.id}/seed`, { pool_captains: captainRegs, captain_order: "weakest_first" });

    const board: DraftBoard = await draftBoard(anonApi, created.id);
    expect(board.session.status).toBe("ready");
    expect(board.players, "the pool is the qualifiers, nobody else").toHaveLength(10);
    expect(board.players.map((p) => p.registration_id).sort((a, b) => a - b)).toEqual(lock.qualified.map((q) => q.registration_id!).sort((a, b) => a - b));
    expect(board.players.filter((p) => p.is_captain).map((p) => p.registration_id).sort()).toEqual(captainRegs.map((c) => c.registration_id).sort());
    expect(board.teams).toHaveLength(PLAYOFF_TEAMS);
    const weakest = userOfReg.get(captainRegs[0].registration_id)!;
    const first = [...board.teams].sort((a, b) => a.draft_position - b.draft_position)[0];
    expect(first.captain_auth_user_id, "the weakest captain picks first").toBe(weakest.id);
  });
});
