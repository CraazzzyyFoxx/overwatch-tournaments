import { poll } from "../support/api";
import { expect, test } from "../support/fixtures";
import { seedCatalog } from "../support/pickban";
import { listEncounters, recalcStandings, seedBracket, setResult, type BracketSeed, type StandingRow } from "../support/flows";
import {
  claimGame,
  expectAdvanced,
  openGame,
  readEncounter,
  reportSeries,
  resultAudit,
  seatOf,
  series,
  setPoints,
  sides,
} from "../support/results";
import type { TestUser } from "../support/users";

async function captains(makeUser: (prefix?: string) => Promise<TestUser>, n: number) {
  return Promise.all(Array.from({ length: n }, () => makeUser("cap")));
}

function standingOf(rows: StandingRow[], teamId: number) {
  const row = rows.find((r) => r.team_id === teamId);
  expect(row, `standing row for team ${teamId}`).toBeTruthy();
  return row!;
}

test.describe("encounter results", () => {
  test("single elimination: agreeing game claims settle a series and the winner advances; a contested game goes to the organizer", async ({
    adminApi,
    admin,
    makeUser,
  }) => {
    const seed = await seedBracket(adminApi, { captains: await captains(makeUser, 4), bestOf: 3, players: false });
    const [semi, other] = seed.encounters.filter((e) => e.round === 1);
    const [home, away] = sides(seed, semi);
    const [outsider] = sides(seed, other);

    // Freeplay: a captain names the map an open position is played on.
    const g1 = await openGame(adminApi, semi.id, 1);
    const { maps } = await seedCatalog(adminApi, 2, 0);
    const named = await home.captain.api.post(`/api/v1/encounters/${semi.id}/games/${g1.id}/map`, { map_id: maps[0].id });
    expect(named.game, "naming the map starts the position").toMatchObject({ map_id: maps[0].id, state: "awaiting_result" });

    // Game 1: the first claim resolves nothing, the matching second one confirms it.
    const first = await claimGame(home.captain, semi.id, g1, { [home.seat]: 3, [away.seat]: 1 });
    expect(first, "first claim waits for the opponent").toMatchObject({ resolved: false, disputed: false });
    const remap = await away.captain.api.raw("POST", `/api/v1/encounters/${semi.id}/games/${g1.id}/map`, { body: { map_id: maps[1].id } });
    expect(remap.status(), "a reported game's map is locked").toBe(409);
    const foreign = await outsider.captain.api.raw("POST", `/api/v1/encounters/${semi.id}/games/${g1.id}/report`, {
      body: { basis_version: 0, results: [{ encounter_team_id: home.seat, score: 0 }, { encounter_team_id: away.seat, score: 3 }] },
    });
    expect(foreign.status(), "a captain of another encounter cannot claim this game").toBe(403);
    const agreed = await claimGame(away.captain, semi.id, g1, { [home.seat]: 3, [away.seat]: 1 });
    expect(agreed).toMatchObject({ resolved: true, disputed: false, game: { state: "confirmed", result_source: "captain_agreement" } });
    const locked = await home.captain.api.raw("POST", `/api/v1/encounters/${semi.id}/games/${g1.id}/report`, {
      body: { basis_version: 0, results: [{ encounter_team_id: home.seat, score: 0 }, { encounter_team_id: away.seat, score: 3 }] },
    });
    expect(locked.status(), "a confirmed game refuses another claim").toBe(409);

    let state = await readEncounter(adminApi, semi.id);
    expect(state.result_status, "one game does not end a Bo3").toBe("none");
    expect(seatOf(state, home.seat).score, "running series score after game 1").toBe(1);
    expect(seatOf(state, away.seat).score).toBe(0);

    // Game 2: the captains disagree -> the game is disputed and the series stays open.
    const g2 = await openGame(adminApi, semi.id, 2);
    await claimGame(home.captain, semi.id, g2, { [home.seat]: 2, [away.seat]: 0 });
    const clash = await claimGame(away.captain, semi.id, g2, { [home.seat]: 0, [away.seat]: 2 });
    expect(clash).toMatchObject({ resolved: false, disputed: true, game: { state: "disputed" } });
    expect((await readEncounter(adminApi, semi.id)).status, "a disputed game leaves the encounter open").toBe("open");

    // The organizer rules on game 2: the series is over through its games.
    const ruled = await adminApi.post(`/api/v1/admin/encounters/${semi.id}/games/${g2.id}/result`, {
      reason: "VOD shows home won",
      results: [
        { encounter_team_id: home.seat, score: 2 },
        { encounter_team_id: away.seat, score: 0 },
      ],
    });
    expect(ruled.game, "admin game result").toMatchObject({ state: "confirmed", result_source: "admin" });

    state = await readEncounter(adminApi, semi.id);
    expect(state, "two confirmed wins settle the Bo3").toMatchObject({ status: "completed", result_status: "confirmed", result_source: "games" });
    expect(seatOf(state, home.seat)).toMatchObject({ score: 2, placement: 1 });
    expect(seatOf(state, away.seat)).toMatchObject({ score: 0, placement: 2 });
    await expectAdvanced(adminApi, seed.encounters, semi.id, 1, home.team.id);

    const audit = await resultAudit(adminApi, semi.id);
    const games = audit.filter((row) => row.action === "game_confirm");
    expect(games.map((row) => row.game_id).sort(), "every confirmed game is journaled").toEqual([g1.id, g2.id].sort());
    // The journal's actor is a players.user id; the organizer's per-game result must name the organizer, not whichever player shares the auth id.
    expect(audit.find((row) => row.game_id === g2.id), "admin per-game result journals the organizer as its actor").toMatchObject({
      actor_name: admin.username,
      source: "admin",
      reason: "VOD shows home won",
    });
  });

  test("series reports: agreement confirms, contradiction disputes; the organizer resolves, reopens and forfeits, all audited with actors", async ({
    adminApi,
    admin,
    makeUser,
  }) => {
    const seed = await seedBracket(adminApi, { captains: await captains(makeUser, 4), bestOf: 3, players: false });
    const [semi, other] = seed.encounters.filter((e) => e.round === 1);
    const [home, away] = sides(seed, semi);
    const [otherHome, otherAway] = sides(seed, other);

    // The default form requires a closeness rating.
    const noCloseness = await home.captain.api.raw("POST", `/api/v1/encounters/${semi.id}/report`, {
      body: { ...series(home.seat, away.seat, 2, 0), closeness: undefined },
    });
    expect(noCloseness.status(), "default report form requires closeness").toBe(422);
    // A Bo3 cannot end 3:0.
    const impossible = await home.captain.api.raw("POST", `/api/v1/encounters/${semi.id}/report`, { body: series(home.seat, away.seat, 3, 0) });
    expect(impossible.status(), "3:0 in a Bo3 is refused").toBe(400);
    expect(await impossible.text()).toContain("series_claim");

    // Agreement on the other semi confirms it with source series_claim.
    const pending = await reportSeries(otherHome.captain, other.id, series(otherAway.seat, otherHome.seat, 2, 1));
    expect(pending.result_status, "one report is pending the opponent").toBe("pending_confirmation");
    const agreed = await reportSeries(otherAway.captain, other.id, series(otherAway.seat, otherHome.seat, 2, 1, { closeness: 9 }));
    expect(agreed).toMatchObject({ result_status: "confirmed", status: "completed" });
    expect((await readEncounter(adminApi, other.id)).result_source).toBe("series_claim");
    const final = await expectAdvanced(adminApi, seed.encounters, other.id, 1, otherAway.team.id);

    // Contradicting reports on this semi -> disputed.
    const homeClaim = await reportSeries(home.captain, semi.id, series(home.seat, away.seat, 2, 0, { comment: "clean 2-0" }));
    expect(homeClaim.result_status).toBe("pending_confirmation");
    const awayClaim = await reportSeries(away.captain, semi.id, series(away.seat, home.seat, 2, 1, { basis_version: homeClaim.result_version }));
    expect(awayClaim.result_status, "contradicting reports dispute the result").toBe("disputed");
    const publicReports = await adminApi.get<{ reports: { encounter_team_id: number; reporter_name: string; comment: string | null }[] }>(
      `/api/v1/encounters/${semi.id}/reports`
    );
    expect(publicReports.reports.map((r) => r.reporter_name).sort(), "reports name their captains").toEqual(
      [home.captain.username, away.captain.username].sort()
    );

    const inbox = await adminApi.get<{ results: { id: number; result_status: string; reports: unknown[] }[] }>("/api/v1/admin/encounter-reports", {
      workspace_id: seed.workspace.id,
      result_status: "disputed",
    });
    expect(inbox.results.map((r) => r.id), "the dispute lands in the organizer's report inbox").toEqual([semi.id]);
    expect(inbox.results[0].reports).toHaveLength(2);

    // Organizer adopts the home report -> confirmed, home advances.
    const adopted = await adminApi.post(`/api/v1/admin/encounters/${semi.id}/result`, { reason: "Checked the VOD", adopt_report_team_id: home.seat });
    expect(adopted).toMatchObject({ result_status: "confirmed", result_source: "admin", status: "completed" });
    await expectAdvanced(adminApi, seed.encounters, semi.id, 1, home.team.id);
    const twice = await adminApi.raw("POST", `/api/v1/admin/encounters/${semi.id}/result`, {
      body: { reason: "again", results: [{ encounter_team_id: home.seat, score: 2 }, { encounter_team_id: away.seat, score: 0 }] },
    });
    expect(twice.status(), "a confirmed result must be reopened first").toBe(409);
    const late = await away.captain.api.raw("POST", `/api/v1/encounters/${semi.id}/report`, { body: series(away.seat, home.seat, 2, 0) });
    expect(late.status(), "captains cannot re-file a confirmed result").toBe(409);

    // Reopen unwinds the advancement.
    const reopened = await adminApi.post(`/api/v1/admin/encounters/${semi.id}/result/reopen`, { reason: "Wrong report adopted" });
    expect(reopened).toMatchObject({ result_status: "none", status: "open" });
    await expect
      .poll(async () => (await readEncounter(adminApi, final.id)).teams.map((t) => t.team_id), { message: "reopen clears the final's seat" })
      .not.toContain(home.team.id);

    // Technical loss for home -> away advances instead.
    const forfeit = await adminApi.post(`/api/v1/admin/encounters/${semi.id}/technical-loss`, { reason: "No show", loser_team_id: home.seat });
    expect(forfeit).toMatchObject({ result_status: "confirmed", status: "completed" });
    expect(forfeit.teams.find((t: { encounter_team_id: number }) => t.encounter_team_id === away.seat).placement).toBe(1);
    await expectAdvanced(adminApi, seed.encounters, semi.id, 1, away.team.id);

    const audit = await resultAudit(adminApi, semi.id);
    expect(
      audit.map((row) => [row.action, row.to_result_status, row.actor_name]),
      "the journal lists every step, newest first, with its actor"
    ).toEqual([
      ["confirm", "confirmed", admin.username],
      ["reopen", "none", admin.username],
      ["confirm", "confirmed", admin.username],
      ["auto_dispute", "disputed", away.captain.username],
      ["auto_pending", "pending_confirmation", home.captain.username],
    ]);
    expect(audit[0].reason).toBe("No show");
    expect(audit[1].reason).toBe("Wrong report adopted");
    expect(audit[2]).toMatchObject({ adopted_team_id: home.seat, reason: "Checked the VOD" });

    const captainAudit = await home.captain.api.raw("GET", `/api/v1/admin/encounters/${semi.id}/result-audit`);
    expect(captainAudit.status(), "captains cannot read the organizer journal").toBe(403);
  });

  test("report form: the organizer's form decides what a captain must file", async ({ adminApi, makeUser }) => {
    const seed = await seedBracket(adminApi, { captains: await captains(makeUser, 2), bestOf: 3, players: false });
    const [match] = seed.encounters;
    const [home, away] = sides(seed, match);
    const url = `/api/v1/admin/tournaments/${seed.tournament.id}/report-form`;

    const defaults = await adminApi.get(url);
    expect(defaults.built_in_fields.closeness, "closeness is required by default").toEqual({ enabled: true, required: true });

    const form = {
      built_in_fields: {
        closeness: { enabled: false, required: false },
        comment: { enabled: true, required: true },
        map_codes: { enabled: false, required: false },
      },
      custom_fields: [{ key: "lobby", label: "Lobby code", required: true }],
    };
    await adminApi.put(url, form);
    expect(await adminApi.get(url)).toMatchObject({
      built_in_fields: form.built_in_fields,
      custom_fields: [{ key: "lobby", label: "Lobby code", required: true, type: "text" }],
    });
    const publicForm = await home.captain.api.get(`/api/v1/encounters/${match.id}/reports`);
    expect(publicForm.form.custom_fields[0].key, "captains get the form with the reports read").toBe("lobby");
    expect((await home.captain.api.raw("PUT", url, { body: form })).status(), "captains cannot edit the form").toBe(403);

    const base = series(home.seat, away.seat, 2, 1, { closeness: undefined });
    const noComment = await home.captain.api.raw("POST", `/api/v1/encounters/${match.id}/report`, { body: { ...base, custom_fields: { lobby: "A1" } } });
    expect(noComment.status(), "comment is required by the form").toBe(422);
    const noLobby = await home.captain.api.raw("POST", `/api/v1/encounters/${match.id}/report`, { body: { ...base, comment: "gg" } });
    expect(noLobby.status(), "the required custom field is enforced").toBe(422);
    expect(await noLobby.text(), "the error names the missing field").toContain("Lobby code");

    const filed = await reportSeries(home.captain, match.id, { ...base, comment: "gg", closeness: 8, custom_fields: { lobby: "A1" } });
    expect(filed.result_status).toBe("pending_confirmation");
    expect(filed.reports[0], "a disabled field is dropped, not stored").toMatchObject({ closeness: null, comment: "gg", custom_fields: { lobby: "A1" } });
  });
});

test.describe("bracket progression and standings", () => {
  test("double elimination: losers drop to the lower bracket and the final standings place all four", async ({ adminApi }) => {
    const seed = await seedBracket(adminApi, { teams: 4, stageType: "double_elimination", bestOf: 1, players: false });
    const all = seed.encounters;
    expect(all.map((e) => e.round).sort((a, b) => a - b), "4-team double elimination layout").toEqual([-2, -1, 1, 1, 2, 3]);
    const [u1, u2] = all.filter((e) => e.round === 1);
    const [[a, d], [b, c]] = [u1, u2].map((e) => [...e.teams].sort((x, y) => x.slot - y.slot).map((t) => t.team_id!));

    // Organizer result in which `teamId` wins 1:0, whatever slot it sits in.
    const win = async (encounterId: number, teamId: number) => {
      const e = await readEncounter(adminApi, encounterId);
      return setResult(adminApi, e, [...e.teams].sort((x, y) => x.slot - y.slot).map((t) => (t.team_id === teamId ? 1 : 0)));
    };
    await win(u1.id, a);
    await win(u2.id, b);
    const upperFinal = await expectAdvanced(adminApi, all, u1.id, 1, a);
    await expectAdvanced(adminApi, all, u2.id, 1, b);
    const lower1 = await expectAdvanced(adminApi, all, u1.id, 2, d);
    await expectAdvanced(adminApi, all, u2.id, 2, c);

    await win(upperFinal.id, a);
    await win(lower1.id, c);
    const lowerFinal = await expectAdvanced(adminApi, all, upperFinal.id, 2, b);
    await expectAdvanced(adminApi, all, lower1.id, 1, c);
    const grandFinal = await expectAdvanced(adminApi, all, upperFinal.id, 1, a);

    await win(lowerFinal.id, b);
    await expectAdvanced(adminApi, all, lowerFinal.id, 1, b);
    await win(grandFinal.id, a);

    const rows = await recalcStandings(adminApi, seed.tournament.id);
    expect(
      [a, b, c, d].map((team) => standingOf(rows, team).position),
      "champion, runner-up, lower-final loser, first eliminated"
    ).toEqual([1, 2, 3, 4]);
    expect([a, b, c, d].map((team) => [standingOf(rows, team).win, standingOf(rows, team).lose])).toEqual([
      [3, 0],
      [2, 2],
      [1, 2],
      [0, 2],
    ]);
  });

  test("swiss: the next round pairs equal records without rematches; standings count the stage's points", async ({ adminApi }) => {
    const seed = await seedBracket(adminApi, { teams: 6, stageType: "swiss", bestOf: 1, players: false, stage: { max_rounds: 3 } });
    await setPoints(adminApi, seed.stage.id, 3, 1, 0);
    const round1 = seed.encounters;
    expect(round1.map((e) => e.round), "swiss generates one round at a time").toEqual([1, 1, 1]);

    const outcomes = [
      [1, 0],
      [1, 1],
      [0, 1],
    ];
    for (const [i, e] of round1.entries()) await setResult(adminApi, e, outcomes[i]);
    const team = (e: (typeof round1)[number], slot: number) => e.teams.find((t) => t.slot === slot)!.team_id!;
    const winners = [team(round1[0], 1), team(round1[2], 2)];
    const drawn = [team(round1[1], 1), team(round1[1], 2)];
    const losers = [team(round1[0], 2), team(round1[2], 1)];

    const round2 = await poll(
      async () => {
        const next = (await listEncounters(adminApi, seed.tournament.id, seed.stage.id)).filter((e) => e.round === 2);
        return next.length === 3 ? next : undefined;
      },
      "swiss round 2 to be paired after round 1 closes"
    );
    const pairs = round2.map((e) => e.teams.map((t) => t.team_id).sort());
    expect(pairs, "the two 1-0 teams meet").toContainEqual([...winners].sort());
    const played = round1.map((e) => e.teams.map((t) => t.team_id).sort().join("-"));
    for (const pair of pairs) expect(played, `no rematch: ${pair.join("-")}`).not.toContain(pair.join("-"));

    const rows = await recalcStandings(adminApi, seed.tournament.id);
    for (const t of winners) expect(standingOf(rows, t), `winner ${t}`).toMatchObject({ win: 1, draw: 0, lose: 0, points: 3 });
    for (const t of drawn) expect(standingOf(rows, t), `drawn ${t}`).toMatchObject({ win: 0, draw: 1, lose: 0, points: 1 });
    for (const t of losers) expect(standingOf(rows, t), `loser ${t}`).toMatchObject({ win: 0, draw: 0, lose: 1, points: 0 });
    expect(winners.map((t) => standingOf(rows, t).position).sort(), "winners lead the table").toEqual([1, 2]);
  });

  test("round robin: standings follow the win/draw/loss points and recalculate after a config change", async ({ adminApi, makeUser }) => {
    const seed: BracketSeed = await seedBracket(adminApi, { teams: 4, stageType: "round_robin", bestOf: 2, players: false });
    await setPoints(adminApi, seed.stage.id, 3, 1, 0);
    const [first, second] = seed.encounters.filter((e) => e.round === 1);
    await setResult(adminApi, first, [1, 1]); // draw
    await setResult(adminApi, second, [2, 0]);
    const slot = (e: typeof first, s: number) => e.teams.find((t) => t.slot === s)!.team_id!;

    let rows = await recalcStandings(adminApi, seed.tournament.id);
    expect(standingOf(rows, slot(second, 1)), "win = 3").toMatchObject({ win: 1, points: 3, position: 1 });
    expect(standingOf(rows, slot(first, 1)), "draw = 1").toMatchObject({ draw: 1, points: 1 });
    expect(standingOf(rows, slot(first, 2)), "draw = 1").toMatchObject({ draw: 1, points: 1 });
    expect(standingOf(rows, slot(second, 2)), "loss = 0").toMatchObject({ lose: 1, points: 0, position: 4 });

    await setPoints(adminApi, seed.stage.id, 2, 0.5, 0);
    rows = await recalcStandings(adminApi, seed.tournament.id);
    expect(standingOf(rows, slot(second, 1)).points, "recalculated win points").toBe(2);
    expect(standingOf(rows, slot(first, 1)).points, "recalculated draw points").toBe(0.5);

    const player = await makeUser("viewer");
    expect((await player.api.raw("POST", `/api/v1/admin/standings/recalculate/${seed.tournament.id}`)).status(), "players cannot recalculate").toBe(403);
  });
});
