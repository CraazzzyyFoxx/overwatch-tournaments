import { type Api, poll } from "../support/api";
import {
  allPairs,
  beat,
  bracketState,
  doubleElimination,
  encounterOf,
  enter,
  groupTable,
  ladder,
  pairings,
  pairKey,
  playBracket,
  rowOf,
  seats,
  seedGroupsToPlayoffs,
  seedOrder,
  singleElimination,
  stageStandings,
  win,
  type BracketModel,
  type ModelMatch,
  type Result,
  type TableStanding,
} from "../support/correctness";
import { expect, test } from "../support/fixtures";
import {
  createStage,
  generateStage,
  listEncounters,
  seedBracket,
  seedTeams,
  waitForJob,
  type Stage,
  type TournamentJob,
} from "../support/flows";
import { openGame, readEncounter, resultAudit, series, setPoints, sides } from "../support/results";
import { createTournament, createWorkspace, setStatus } from "../support/seed";

/**
 * Tournament-engine correctness, end to end over the gateway: brackets laid out
 * by the documented rules, every result landing where it must, and standings /
 * placements equal to what the entered results imply. Expectations come from the
 * reference models in support/correctness.ts, never from the API under test.
 */

/** The better seed wins, except a round-1 match whose seed indices sum to a multiple of 3: an upset. */
function seededPick(seeds: number[]) {
  return (home: number, away: number, round: number) => {
    const [fav, dog] = seeds.indexOf(home) < seeds.indexOf(away) ? [home, away] : [away, home];
    return round === 1 && (seeds.indexOf(home) + seeds.indexOf(away)) % 3 === 0 ? dog : fav;
  };
}

/** Elimination standings: every seeded team at the model's place with its W/L. */
async function expectPlacements(api: Api, tournamentId: number, stageId: number, seeds: number[], model: BracketModel) {
  const rows = await stageStandings(api, tournamentId, stageId);
  const places = model.placements();
  expect(
    seeds.map((t) => [t, rowOf(rows, t).position, rowOf(rows, t).win, rowOf(rows, t).lose]),
    "place, wins and losses of every team"
  ).toEqual(seeds.map((t) => [t, places.get(t), model.record(t).win, model.record(t).lose]));
  return rows;
}

test.describe("single elimination", () => {
  for (const n of [4, 5, 6, 8]) {
    test(`${n} teams: 1-vs-N seeding, byes to the top seeds, winners take their feeder's slot, places from the bottom`, async ({ adminApi }) => {
      const seed = await seedBracket(adminApi, { teams: n, stageType: "single_elimination", bestOf: 1, players: false });
      const seeds = seedOrder(seed.stage);
      expect([...seeds].sort(), "every team is seeded once").toEqual(seed.teams.map((t) => t.id).sort());
      const size = 2 ** Math.ceil(Math.log2(n));
      const s = (rank: number) => seeds[rank - 1];

      // Layout: size - n byes go to the top seeds, who sit in round 2 from the start.
      const round1 = seed.encounters.filter((e) => e.round === 1);
      expect(round1, "round 1 plays the field down to a power of two").toHaveLength(n - size / 2);
      const byes = seeds.slice(0, size - n);
      const inRound1 = round1.flatMap((e) => seats(e));
      for (const team of byes) {
        expect(inRound1, `top seed ${seeds.indexOf(team) + 1} has a bye`).not.toContain(team);
        expect(seed.encounters.filter((e) => e.round === 2).flatMap((e) => seats(e)), `bye of seed ${seeds.indexOf(team) + 1} is seated in round 2`).toContain(team);
      }
      if (n === 8) {
        expect(round1.map((e) => seats(e).join("-")).sort(), "1-8, 4-5, 2-7, 3-6").toEqual(
          [`${s(1)}-${s(8)}`, `${s(4)}-${s(5)}`, `${s(2)}-${s(7)}`, `${s(3)}-${s(6)}`].sort()
        );
      }
      if (n === 5) {
        expect(round1.map((e) => seats(e)), "only seeds 4 and 5 play round 1").toEqual([[s(4), s(5)]]);
        expect(bracketState(seed.encounters), "seed 1 waits for the 4-5 winner, seeds 2 and 3 meet").toEqual(
          [`1:${s(4)}-${s(5)}`, `2:${s(1)}--`, `2:${s(2)}-${s(3)}`].sort()
        );
      }

      const model = singleElimination(seeds);
      const pick = seededPick(seeds);
      if (n === 8) {
        // Semis decided, final open: the beaten semi-finalists are 3rd, the finalists not placed yet.
        await playBracket(adminApi, seed.tournament.id, seed.stage.id, model, pick, { limit: 6 });
        const rows = await stageStandings(adminApi, seed.tournament.id, seed.stage.id);
        const [finalist1, finalist2] = model.seatsOf(model.ready()[0]);
        const places = model.placements();
        for (const team of seeds) {
          const expected = team === finalist1 || team === finalist2 ? 0 : places.get(team);
          expect(rowOf(rows, team).position, `interim place of seed ${seeds.indexOf(team) + 1}`).toBe(expected);
        }
      }
      await playBracket(adminApi, seed.tournament.id, seed.stage.id, model, pick);
      await expectPlacements(adminApi, seed.tournament.id, seed.stage.id, seeds, model);
    });
  }
});

test.describe("double elimination", () => {
  for (const n of [6, 8]) {
    test(`${n} teams: losers drop into their lower slot, two losses eliminate, places by elimination round`, async ({ adminApi }) => {
      const seed = await seedBracket(adminApi, { teams: n, stageType: "double_elimination", bestOf: 1, players: false });
      const seeds = seedOrder(seed.stage);
      const model = doubleElimination(seeds);
      expect(bracketState(seed.encounters), "generated layout equals the documented one").toEqual(model.state());
      const live = await playBracket(adminApi, seed.tournament.id, seed.stage.id, model, seededPick(seeds));

      // Second chance: two losses eliminate. Only the Grand Final's loser can leave with one -- the
      // upper champion beaten once in a no_reset final -- and the champion lost at most once.
      const grandFinal = model.matches[model.matches.length - 1];
      for (const team of seeds) {
        const { lose } = model.record(team);
        const message = `losses of seed ${seeds.indexOf(team) + 1}`;
        if (team === grandFinal.winner) expect(lose, message).toBeLessThanOrEqual(1);
        else if (team === grandFinal.loser && team === model.seatsOf(grandFinal)[0]) expect(lose, message).toBe(1);
        else expect(lose, message).toBe(2);
      }
      // Cross-drop: no first dropout-round match of the lower bracket is a rematch.
      const dropoutRound = model.matches.filter((m) => m.round === -2);
      const earlier = model.matches.filter((m) => m.round === 1 || m.round === -1).map((m) => [m.winner, m.loser].sort().join("-"));
      for (const m of dropoutRound) expect(earlier, `lower round 2 ${model.seatsOf(m).join("-")} is a first meeting`).not.toContain([m.winner, m.loser].sort().join("-"));
      expect(live.some((e) => e.round === grandFinal.round + 1), "no_reset: no second Grand Final").toBe(false);

      await expectPlacements(adminApi, seed.tournament.id, seed.stage.id, seeds, model);
    });
  }

  test("4 teams with_reset: the lower champion winning the Grand Final forces a Reset; correcting the Grand Final drops it", async ({ adminApi }) => {
    const seed = await seedBracket(adminApi, {
      teams: 4,
      stageType: "double_elimination",
      bestOf: 1,
      players: false,
      stage: { de_grand_final_type: "with_reset" },
    });
    const seeds = seedOrder(seed.stage);
    const model = doubleElimination(seeds);
    const gf = model.matches[model.matches.length - 1];
    const favourite = seededPick(seeds);
    // The Grand Final goes to slot 2 (the lower champion), its Reset to slot 1 (the upper one), the rest to the better seed.
    const pick = (home: number, away: number, round: number) => (round === gf.round ? away : round > gf.round ? home : favourite(home, away, round));
    const addReset = (m: ModelMatch) => {
      if (m === gf && m.winner === model.seatsOf(gf)[1]) model.play({ loserOf: gf.id }, { winnerOf: gf.id }, gf.round + 1);
    };
    const live = await playBracket(adminApi, seed.tournament.id, seed.stage.id, model, pick, { after: addReset });
    expect(model.matches[model.matches.length - 1].round, "a Reset was materialised after the Grand Final").toBe(gf.round + 1);
    // The Reset is the final now: the upper champion who won it is 1st, the lower champion 2nd.
    await expectPlacements(adminApi, seed.tournament.id, seed.stage.id, seeds, model);

    // Correction: the Grand Final really went to the upper champion -> the played Reset is unwound and dropped.
    const gfLive = live.find((e) => e.round === gf.round)!;
    const resetLive = live.find((e) => e.round === gf.round + 1)!;
    const upper = seats(gfLive)[0]!;
    await adminApi.post(`/api/v1/admin/encounters/${gfLive.id}/result/reopen`, { reason: "wrong winner" });
    await win(adminApi, await readEncounter(adminApi, gfLive.id), upper);
    await expect
      .poll(async () => (await listEncounters(adminApi, seed.tournament.id, seed.stage.id)).some((e) => e.id === resetLive.id), {
        message: "the Reset is dropped once the upper champion wins the Grand Final",
      })
      .toBe(false);
    model.undo(gf);
    model.matches.pop();
    const [home, away] = model.seatsOf(gf) as [number, number];
    model.decide(home, away, upper);
    // Nothing is left to play; this asserts the corrected bracket against the model.
    await playBracket(adminApi, seed.tournament.id, seed.stage.id, model, pick);
    const rows = await expectPlacements(adminApi, seed.tournament.id, seed.stage.id, seeds, model);
    expect(rowOf(rows, upper).position, "the upper champion wins the tournament").toBe(1);
  });
});

const POINTS = { win: 3, draw: 1, loss: 0 };
/** `RULE_PRESET_DEFAULTS` of standings/service.py, the documented default orders. */
const ROUND_ROBIN_ORDER = ["points", "head_to_head", "median_buchholz", "match_wins", "score_differential"];
const SWISS_ORDER = ["points", "median_buchholz", "buchholz", "match_wins", "score_differential"];

test.describe("round robin", () => {
  test("4 teams: every pair once over 3 rounds; a half-played round counts for nobody; head-to-head splits teams level on points", async ({ adminApi }) => {
    const seed = await seedBracket(adminApi, { teams: 4, stageType: "round_robin", bestOf: 1, players: false });
    await setPoints(adminApi, seed.stage.id, POINTS.win, POINTS.draw, POINTS.loss);
    const teams = seedOrder(seed.stage);
    const [a, b, c, d] = teams;
    const all = seed.encounters;
    expect(all.map((e) => pairKey(...seats(e))).sort(), "every pair meets exactly once").toEqual(allPairs(teams));
    expect([...new Set(all.map((e) => e.round))].sort(), "n - 1 rounds").toEqual([1, 2, 3]);
    for (const round of [1, 2, 3]) {
      const playing = all.filter((e) => e.round === round).flatMap((e) => seats(e));
      expect(playing.sort(), `round ${round} seats every team once`).toEqual([...teams].sort());
    }

    // a and b finish on 6, d and c on 3; inside each pair the winner of their meeting is ahead.
    const plan = [beat(a, b), beat(c, a), beat(a, d), beat(b, c), beat(b, d), beat(d, c)];
    const [first] = all.filter((e) => e.round === 1);
    const firstResult = plan.find((r) => pairKey(r.home, r.away) === pairKey(...seats(first)))!;
    await enter(adminApi, all, firstResult);
    let rows = await stageStandings(adminApi, seed.tournament.id, seed.stage.id);
    expect(rows.map((r) => r.matches), "standings count only closed rounds").toEqual([0, 0, 0, 0]);
    for (const r of plan) if (r !== firstResult) await enter(adminApi, all, r);

    rows = await stageStandings(adminApi, seed.tournament.id, seed.stage.id);
    const table = groupTable(teams, plan, POINTS, ROUND_ROBIN_ORDER);
    expect(table.map((r) => r.team), "a over b and d over c, each on head-to-head").toEqual([a, b, d, c]);
    expect(rows.map((r) => [r.team_id, r.position, r.matches, r.win, r.draw, r.lose, r.points, r.tb])).toEqual(
      table.map((r, i) => [r.team, i + 1, r.matches, r.win, r.draw, r.lose, r.points, r.head_to_head])
    );
  });

  test("5 teams: a bye every round, draws, the stage's own points and its configured tiebreak order", async ({ adminApi }) => {
    const order = ["points", "score_differential", "match_wins"];
    const seed = await seedBracket(adminApi, {
      teams: 5,
      stageType: "round_robin",
      bestOf: 3,
      players: false,
      stage: { tiebreak_order: order, scoring: { win: POINTS.win, draw: POINTS.draw, loss: POINTS.loss } },
    });
    const teams = seedOrder(seed.stage);
    const all = seed.encounters;
    expect(all.map((e) => pairKey(...seats(e))).sort(), "every pair meets exactly once").toEqual(allPairs(teams));
    const rounds = [...new Set(all.map((e) => e.round))].sort();
    expect(rounds, "an odd field needs n rounds").toEqual([1, 2, 3, 4, 5]);
    const idle = rounds.map((round) => teams.filter((t) => !all.filter((e) => e.round === round).flatMap((e) => seats(e)).includes(t)));
    expect(idle.map((sitting) => sitting.length), "one team sits out each round").toEqual([1, 1, 1, 1, 1]);
    expect(idle.flat().sort(), "every team sits out exactly once").toEqual([...teams].sort());

    // Roles by finish x1..x5; ids run x3, x2, x1, x5, x4 so the team-id fallback would order every tie the other way.
    const [x3, x2, x1, x5, x4] = teams;
    const plan: Result[] = [
      { home: x3, away: x2, hs: 2, as: 1 },
      { home: x1, away: x3, hs: 2, as: 0 },
      { home: x2, away: x1, hs: 2, as: 1 },
      { home: x3, away: x4, hs: 2, as: 1 },
      { home: x2, away: x4, hs: 2, as: 1 },
      { home: x1, away: x4, hs: 2, as: 0 },
      { home: x3, away: x5, hs: 1, as: 1 },
      { home: x2, away: x5, hs: 1, as: 1 },
      { home: x1, away: x5, hs: 1, as: 1 },
      { home: x4, away: x5, hs: 2, as: 0 },
    ];
    for (const r of plan) await enter(adminApi, all, r);
    const rows = await stageStandings(adminApi, seed.tournament.id, seed.stage.id);
    const table = groupTable(teams, plan, POINTS, order);
    // x1, x2, x3 on 7 split by map difference (+3, +1, 0); x4 and x5 on 3 and -2 split by match wins (1 vs 0).
    expect(table.map((r) => r.team)).toEqual([x1, x2, x3, x4, x5]);
    expect(rows.map((r) => [r.team_id, r.position, r.points, r.win, r.draw, r.lose, r.score_differential])).toEqual(
      table.map((r, i) => [r.team, i + 1, r.points, r.win, r.draw, r.lose, r.score_differential])
    );
  });
});

/** Polls until `round` of a Swiss stage is paired with `count` encounters (the standings job pairs it). */
async function swissRound(api: Api, tournamentId: number, stageId: number, round: number, count: number) {
  return poll(
    async () => {
      const list = (await listEncounters(api, tournamentId, stageId)).filter((e) => e.round === round);
      return list.length === count ? list : undefined;
    },
    `swiss round ${round} to be paired`,
    60_000
  );
}

test.describe("swiss", () => {
  test("8 teams, 3 rounds: Monrad round 1, pairing inside score groups, no rematch, a Buchholz-ordered table", async ({ adminApi }) => {
    const seed = await seedBracket(adminApi, { teams: 8, stageType: "swiss", bestOf: 1, players: false, stage: { max_rounds: 3 } });
    await setPoints(adminApi, seed.stage.id, POINTS.win, POINTS.draw, POINTS.loss);
    const seeds = seedOrder(seed.stage);
    const s = (rank: number) => seeds[rank - 1];
    const favourite = seededPick(seeds);
    const results: Result[] = [];
    const played = new Set<string>();
    for (let round = 1; round <= 3; round++) {
      const encounters = await swissRound(adminApi, seed.tournament.id, seed.stage.id, round, 4);
      const pairs = encounters.map((e) => seats(e) as [number, number]);
      expect(pairs.flat().sort(), `round ${round} seats every team once`).toEqual([...seeds].sort());
      for (const [h, a] of pairs) expect(played.has(pairKey(h, a)), `round ${round}: ${h}-${a} is a first meeting`).toBe(false);
      if (round === 1) {
        expect(pairs.map((p) => pairKey(...p)).sort(), "Monrad: top half meets bottom half, 1-5 2-6 3-7 4-8").toEqual(
          [pairKey(s(1), s(5)), pairKey(s(2), s(6)), pairKey(s(3), s(7)), pairKey(s(4), s(8))].sort()
        );
      } else {
        // Monrad pairs inside score groups; a pair across groups only where no rematch-free round
        // avoids it -- among the rounds that leave the next one pairable, which the engine weighs first.
        const points = new Map(groupTable(seeds, results, POINTS, SWISS_ORDER).map((r) => [r.team, r.points]));
        const floats = (option: [number, number][]) => option.filter(([h, a]) => points.get(h) !== points.get(a)).length;
        const options = pairings(seeds, played);
        const viable = options.filter((option) => pairings(seeds, new Set([...played, ...option.map((p) => pairKey(...p))])).length > 0);
        const fewest = Math.min(...(viable.length ? viable : options).map(floats));
        expect(floats(pairs), `round ${round}: pairs across score groups (${pairs.map((p) => p.map((t) => points.get(t)).join(":")).join(", ")})`).toBe(fewest);
      }
      for (const [i, [h, a]] of pairs.entries()) {
        // Round 2's first match is drawn; the rest go to the better seed, with round-1 upsets.
        const winner = favourite(h, a, round);
        const r = round === 2 && i === 0 ? { home: h, away: a, hs: 1, as: 1 } : beat(winner, winner === h ? a : h);
        await enter(adminApi, encounters, r);
        results.push(r);
        played.add(pairKey(h, a));
      }
    }
    const rows = await stageStandings(adminApi, seed.tournament.id, seed.stage.id);
    expect((await listEncounters(adminApi, seed.tournament.id, seed.stage.id)).some((e) => e.round > 3), "max_rounds: no fourth round").toBe(false);
    expect((await adminApi.get<Stage>(`/api/v1/admin/stages/${seed.stage.id}`)).is_completed, "the stage is complete after its last round").toBe(true);
    const table = groupTable(seeds, results, POINTS, SWISS_ORDER);
    expect(rows.map((r) => [r.team_id, r.position, r.points, r.win, r.draw, r.lose, r.buchholz, r.full_buchholz])).toEqual(
      table.map((r, i) => [r.team, i + 1, r.points, r.win, r.draw, r.lose, r.median_buchholz, r.buchholz])
    );
  });

  test("7 teams: one bye a round to the lowest team without one, never twice, worth a win", async ({ adminApi }) => {
    const seed = await seedBracket(adminApi, { teams: 7, stageType: "swiss", bestOf: 1, players: false, stage: { max_rounds: 3 } });
    await setPoints(adminApi, seed.stage.id, POINTS.win, POINTS.draw, POINTS.loss);
    const seeds = seedOrder(seed.stage);
    const favourite = seededPick(seeds);
    const byes = new Map<number, number>();
    const results: Result[] = [];
    const played = new Set<string>();
    for (let round = 1; round <= 3; round++) {
      const encounters = await swissRound(adminApi, seed.tournament.id, seed.stage.id, round, 3);
      const pairs = encounters.map((e) => seats(e) as [number, number]);
      const idle = seeds.filter((t) => !pairs.flat().includes(t));
      expect(idle, `round ${round}: exactly one team has the bye`).toHaveLength(1);
      expect(byes.has(idle[0]), `round ${round}: ${idle[0]} gets no second bye`).toBe(false);
      if (round === 1) expect(idle[0], "round 1: the lowest seed sits out").toBe(seeds[6]);
      byes.set(idle[0], 1);
      for (const [h, a] of pairs) {
        expect(played.has(pairKey(h, a)), `round ${round}: ${h}-${a} is a first meeting`).toBe(false);
        const winner = favourite(h, a, round);
        const r = beat(winner, winner === h ? a : h);
        await enter(adminApi, encounters, r);
        results.push(r);
        played.add(pairKey(h, a));
      }
    }
    const rows = await stageStandings(adminApi, seed.tournament.id, seed.stage.id);
    const table = groupTable(seeds, results, POINTS, SWISS_ORDER, byes);
    expect(rows.map((r) => [r.team_id, r.position, r.matches, r.points, r.buchholz, r.full_buchholz])).toEqual(
      table.map((r, i) => [r.team, i + 1, r.matches, r.points, r.median_buchholz, r.buchholz])
    );
  });
});

/** Everything a recalculation writes, minus the row ids it regenerates. */
async function standingsSnapshot(api: Api, tournamentId: number) {
  const rows = await api.get<TableStanding[]>(`/api/v1/tournaments/${tournamentId}/standings`);
  return rows
    .map((r) => [r.stage_id, r.stage_item_id, r.team_id, r.position, r.overall_position, r.matches, r.win, r.draw, r.lose, r.points, r.buchholz, r.full_buchholz, r.tb, r.score_differential, r.tie_group])
    .sort((x, y) => String(x).localeCompare(String(y)));
}

async function recalculate(api: Api, tournamentId: number) {
  await waitForJob(api, await api.post<TournamentJob>(`/api/v1/admin/standings/recalculate/${tournamentId}`, undefined, 202));
}

test("groups → playoffs: top 2 cross-seed A1-B2 / B1-A2 only once the groups close; a group correction re-seeds until the playoff starts", async ({ adminApi }) => {
  test.setTimeout(600_000);
  const { tournament, groupStage, playoff, groupA, groupB, encounters: groupEncounters } = await seedGroupsToPlayoffs(adminApi);
  const [a1, a2, a3, a4] = groupA;
  const [b1, b2, b3, b4] = groupB;
  const planA = ladder(groupA);
  const planB = ladder(groupB);
  for (const r of [...planA, ...planB.slice(0, 5)]) await enter(adminApi, groupEncounters, r);

  // One group match still open: activation refuses to freeze the playoff seeds.
  const refused = await adminApi.post<TournamentJob>(`/api/v1/admin/stages/${playoff.id}/activate-and-generate`, undefined, 202);
  const outcome = await poll(
    async () => {
      const job = await adminApi.get<TournamentJob>(`/api/v1/admin/tournament-jobs/${refused.id}`);
      return job.status === "pending" || job.status === "running" ? undefined : job;
    },
    "the early playoff generation to settle"
  );
  expect(outcome.status, "playoff generation before the groups close").toBe("failed");
  expect(outcome.error).toContain("upstream_stages_not_completed");
  expect(await listEncounters(adminApi, tournament.id, playoff.id), "no playoff match before the groups close").toHaveLength(0);

  await enter(adminApi, groupEncounters, planB[5]);
  let rows = await stageStandings(adminApi, tournament.id, groupStage.id);
  const groupOrder = (item: number) => rows.filter((r) => r.stage_item_id === item).map((r) => r.team_id);
  const [itemA, itemB] = [...groupStage.items].sort((x, y) => x.id - y.id).map((item) => item.id);
  expect(groupOrder(itemA)).toEqual(groupTable(groupA, planA, POINTS, ROUND_ROBIN_ORDER).map((r) => r.team));
  expect(groupOrder(itemB)).toEqual(groupTable(groupB, planB, POINTS, ROUND_ROBIN_ORDER).map((r) => r.team));
  expect((await adminApi.get<Stage>(`/api/v1/admin/stages/${groupStage.id}`)).is_completed, "both groups closed").toBe(true);

  await generateStage(adminApi, playoff.id);
  const firstRound = async () =>
    (await listEncounters(adminApi, tournament.id, playoff.id))
      .filter((e) => e.round === 1)
      .map((e) => seats(e).join("-"))
      .sort();
  expect(await firstRound(), "cross-seeding: A1 vs B2, B1 vs A2").toEqual([`${a1}-${b2}`, `${b1}-${a2}`].sort());

  // A correction while the playoff is untouched: a3 really beat a2, so a3 is A2 now and takes the seat.
  const fixed = encounterOf(groupEncounters, a2, a3);
  await adminApi.post(`/api/v1/admin/encounters/${fixed.id}/result/reopen`, { reason: "score sheet swapped" });
  planA[3] = beat(a3, a2);
  await enter(adminApi, [await readEncounter(adminApi, fixed.id)], planA[3]);
  await expect
    .poll(firstRound, { message: "the re-ranked A2 is re-seeded into the untouched playoff", timeout: 60_000 })
    .toEqual([`${a1}-${b2}`, `${b1}-${a3}`].sort());
  rows = await stageStandings(adminApi, tournament.id, groupStage.id);
  expect(groupOrder(itemA), "group A after the correction").toEqual(groupTable(groupA, planA, POINTS, ROUND_ROBIN_ORDER).map((r) => r.team));
  expect(groupOrder(itemA)).toEqual([a1, a3, a2, a4]);

  // Once the playoff has a result, a group correction is refused: the seed is frozen into a running bracket.
  const playoffRound1 = await listEncounters(adminApi, tournament.id, playoff.id);
  await win(adminApi, encounterOf(playoffRound1, a1, b2), a1);
  const late = await adminApi.raw("POST", `/api/v1/admin/encounters/${encounterOf(groupEncounters, a1, a4).id}/result/reopen`, {
    body: { reason: "too late" },
  });
  expect(late.status(), "a group correction after the playoff started").toBe(409);
  expect(await late.text()).toContain("downstream stage already in progress");

  await win(adminApi, encounterOf(playoffRound1, b1, a3), b1);
  const final = await poll(
    async () => (await listEncounters(adminApi, tournament.id, playoff.id)).find((e) => e.round === 2 && seats(e).every((t) => t !== null)),
    "the playoff final to be seated"
  );
  expect(seats(final), "semi 1's winner in slot 1, semi 2's in slot 2").toEqual([a1, b1]);
  await win(adminApi, final, a1);

  // Overall: the playoff decides 1-4 (two 3rds); the rest follow by group place, then points/tb/Buchholz across groups.
  await recalculate(adminApi, tournament.id);
  const all = await adminApi.get<TableStanding[]>(`/api/v1/tournaments/${tournament.id}/standings`);
  const overall = (team: number, stageId: number) => all.find((r) => r.team_id === team && r.stage_id === stageId)!.overall_position;
  expect([a1, b1, b2, a3].map((t) => overall(t, playoff.id)), "playoff places").toEqual([1, 2, 3, 3]);
  // a2/b3 are both 3rd on 3 points with equal tiebreakers, a4/b4 both 4th on 0: each pair shares a band.
  expect([a2, b3].map((t) => overall(t, groupStage.id)).sort(), "group 3rds after the playoff teams").toEqual([5, 6]);
  expect([a4, b4].map((t) => overall(t, groupStage.id)).sort(), "group 4ths last").toEqual([7, 8]);

  // Recalculation is idempotent, and finishing the tournament keeps every row.
  const before = await standingsSnapshot(adminApi, tournament.id);
  await recalculate(adminApi, tournament.id);
  expect(await standingsSnapshot(adminApi, tournament.id), "a second recalculation changes nothing").toEqual(before);
  const finished = await adminApi.post(`/api/v1/admin/tournaments/${tournament.id}/finish`);
  expect(finished.status).toBe("completed");
  expect(await standingsSnapshot(adminApi, tournament.id), "finishing keeps the standings").toEqual(before);
  await recalculate(adminApi, tournament.id);
  expect(await standingsSnapshot(adminApi, tournament.id), "a recalculation after finishing changes nothing").toEqual(before);
});

// "Both modes avoid same-group rematches in the first playoff round" (wire_from_groups, WireFromGroupsRequest,
// the auto-wire comment). Three groups sending two leave two byes; the explicit wire defaults to `cross`.
for (const [groupCount, wiring] of [
  [3, "auto-wire"],
  [4, "auto-wire"],
  [2, "explicit wire, default mode"],
] as const) {
  test(`playoff seeding from ${groupCount} groups (${wiring}) never opens with two teams of one group; byes go to group winners`, async ({ adminApi }) => {
    const ws = await createWorkspace(adminApi);
    const tournament = await createTournament(adminApi, ws.id);
    const teams = await seedTeams(adminApi, tournament.id, groupCount * 2, { players: false });
    const explicit = wiring !== "auto-wire";
    const created = await createStage(
      adminApi,
      tournament.id,
      teams.map((t) => t.id),
      { stageType: "round_robin", groups: groupCount, bestOf: 1, extra: explicit ? {} : { advance_count: 2 } }
    );
    await generateStage(adminApi, created.id);
    const playoff = await adminApi.post<Stage>(
      `/api/v1/admin/stages/tournament/${tournament.id}`,
      { name: "Playoffs", stage_type: "single_elimination", best_of: { default: 1 }, order: 1 },
      201
    );
    await adminApi.post(`/api/v1/admin/stages/${playoff.id}/items`, { name: "Bracket", type: "single_bracket", order: 0 }, 201);
    await setStatus(adminApi, tournament.id, "live", true);

    const groupStage = await adminApi.get<Stage>(`/api/v1/admin/stages/${created.id}`);
    const groupOf = new Map(groupStage.items.flatMap((item) => item.inputs.map((input) => [input.team_id!, item.name])));
    // Each group is two teams: slot 1 wins its one match and is the group winner.
    for (const e of await listEncounters(adminApi, tournament.id, created.id)) await win(adminApi, e, seats(e)[0]!);
    const rows = await stageStandings(adminApi, tournament.id, created.id);
    const winners = new Set(rows.filter((r) => r.position === 1).map((r) => r.team_id));
    if (explicit) await adminApi.post(`/api/v1/admin/stages/${playoff.id}/wire-from-groups`, { source_stage_id: created.id, top: 2 });
    await generateStage(adminApi, playoff.id);

    const firstRound = (await listEncounters(adminApi, tournament.id, playoff.id)).filter((e) => e.round === 1).map((e) => seats(e) as [number, number]);
    const n = groupCount * 2;
    expect(firstRound.length, "round 1 plays the field down to a power of two").toBe(n - 2 ** Math.ceil(Math.log2(n)) / 2);
    for (const [home, away] of firstRound) {
      expect(groupOf.get(home), `round 1: ${groupOf.get(home)} vs ${groupOf.get(away)}`).not.toBe(groupOf.get(away));
    }
    const byes = teams.map((t) => t.id).filter((t) => !firstRound.flat().includes(t));
    for (const team of byes) expect(winners.has(team), `bye of ${team} (${groupOf.get(team)}) goes to a group winner`).toBe(true);
  });
}

test("best-of: games sum to the series score, a Bo3 cannot be claimed 2:2, a forfeit scores a winning series, map difference counts games", async ({
  adminApi,
  makeUser,
}) => {
  test.setTimeout(600_000);
  const captains = await Promise.all([0, 1, 2, 3].map(() => makeUser("cap")));
  const order = ["points", "map_differential"];
  const seed = await seedBracket(adminApi, {
    captains,
    stageType: "round_robin",
    players: false,
    stage: { best_of: { default: 3, by_round: { 2: 5 } }, tiebreak_order: order },
  });
  await setPoints(adminApi, seed.stage.id, POINTS.win, POINTS.draw, POINTS.loss);
  const teams = seedOrder(seed.stage);
  const all = seed.encounters;
  expect(all.map((e) => [e.round, e.best_of]), "round 2 is a Bo5, the others Bo3").toEqual(all.map((e) => [e.round, e.round === 2 ? 5 : 3]));

  /** Organizer result of one map: the home side wins it 3:1, or loses it 1:3. */
  const map = async (encounterId: number, position: number, homeWins: boolean) => {
    const game = await openGame(adminApi, encounterId, position);
    const [home, away] = [...(await readEncounter(adminApi, encounterId)).teams].sort((x, y) => x.slot - y.slot);
    await adminApi.post(`/api/v1/admin/encounters/${encounterId}/games/${game.id}/result`, {
      reason: "map result",
      results: [
        { encounter_team_id: home.id, score: homeWins ? 3 : 1 },
        { encounter_team_id: away.id, score: homeWins ? 1 : 3 },
      ],
    });
  };
  const playMaps = async (encounterId: number, homeWins: boolean[]) => {
    for (const [i, won] of homeWins.entries()) await map(encounterId, i + 1, won);
    const state = await readEncounter(adminApi, encounterId);
    const homeMaps = homeWins.filter(Boolean).length;
    const awayMaps = homeWins.length - homeMaps;
    expect(state, "the last map settles the series through its games").toMatchObject({ status: "completed", result_status: "confirmed", result_source: "games" });
    expect(
      [...state.teams].sort((x, y) => x.slot - y.slot).map((t) => [t.score, t.placement]),
      `${homeMaps}:${awayMaps} in maps is the series score, the side with more maps first`
    ).toEqual([
      [homeMaps, homeMaps > awayMaps ? 1 : 2],
      [awayMaps, homeMaps > awayMaps ? 2 : 1],
    ]);
    const [home, away] = seats(state);
    return { home: home!, away: away!, hs: homeMaps, as: awayMaps };
  };

  const [bo3, forfeited] = all.filter((e) => e.round === 1);
  const [bo5, bo5b] = all.filter((e) => e.round === 2);
  const results: Result[] = [await playMaps(bo3.id, [true, false, true]), await playMaps(bo5.id, [true, false, false, true, false])];

  // A captain's claim has to be a score the Bo3 can end on.
  const [home, away] = sides(seed, forfeited);
  for (const [won, lost, code] of [
    [2, 2, "series_claim_games_played"],
    [1, 1, "series_claim_not_final"],
  ] as const) {
    const claim = await home.captain.api.raw("POST", `/api/v1/encounters/${forfeited.id}/report`, { body: series(home.seat, away.seat, won, lost) });
    expect(claim.status(), `${won}:${lost} claimed in a Bo3`).toBe(400);
    expect(await claim.text()).toContain(code);
  }
  // Forfeit with nothing played: a winning Bo3 series for the other side, 0:2.
  const forfeit = await adminApi.post<{ teams: { encounter_team_id: number; score: number; placement: number }[] }>(
    `/api/v1/admin/encounters/${forfeited.id}/technical-loss`,
    { reason: "no show", loser_team_id: home.seat }
  );
  expect(forfeit.teams.map((t) => [t.encounter_team_id, t.score, t.placement]).sort(), "forfeit score").toEqual(
    [
      [home.seat, 0, 2],
      [away.seat, 2, 1],
    ].sort()
  );
  results.push({ home: home.team.id, away: away.team.id, hs: 0, as: 2 });

  // The rest by organizer result.
  const [last1, last2] = all.filter((e) => e.round === 3);
  for (const [e, hs, as] of [
    [bo5b, 2, 3],
    [last1, 2, 0],
    [last2, 1, 2],
  ] as const) {
    const [h, a] = seats(e);
    await enter(adminApi, all, { home: h!, away: a!, hs, as });
    results.push({ home: h!, away: a!, hs, as });
  }
  const rows = await stageStandings(adminApi, seed.tournament.id, seed.stage.id);
  const table = groupTable(teams, results, POINTS, order);
  expect(rows.map((r) => [r.team_id, r.position, r.points, r.win, r.lose, r.score_differential])).toEqual(
    table.map((r, i) => [r.team, i + 1, r.points, r.win, r.lose, r.score_differential])
  );
});

test("a reopened semi-final whose winner already won the final unwinds the final; the corrected winner advances and the places follow", async ({ adminApi }) => {
  const seed = await seedBracket(adminApi, { teams: 4, stageType: "single_elimination", bestOf: 1, players: false });
  const seeds = seedOrder(seed.stage);
  const s = (rank: number) => seeds[rank - 1];
  const better = (h: number, a: number) => (seeds.indexOf(h) < seeds.indexOf(a) ? h : a);
  const model = singleElimination(seeds);
  const live = await playBracket(adminApi, seed.tournament.id, seed.stage.id, model, better);
  const semi = encounterOf(live, s(1), s(4));
  const final = live.find((e) => e.round === 2)!;
  expect(seats(final), "seed 1 won semi 1 and sits in the final's slot 1").toEqual([s(1), s(2)]);

  await adminApi.post(`/api/v1/admin/encounters/${semi.id}/result/reopen`, { reason: "wrong winner entered" });
  model.undo(model.matches.find((m) => m.round === 1 && model.seatsOf(m).includes(s(1)))!);
  await expect
    .poll(async () => {
      const read = await readEncounter(adminApi, final.id);
      return [read.status, read.result_status, seats(read)];
    }, { message: "the final loses semi 1's winner and its own played result" })
    .toEqual(["open", "none", [null, s(2)]]);
  expect((await resultAudit(adminApi, final.id)).map((row) => row.reason), "the final's journal names the cascade").toContain("bracket_reset");
  expect(bracketState(await listEncounters(adminApi, seed.tournament.id, seed.stage.id))).toEqual(model.state());

  // Seed 4 really won the semi: it takes slot 1 of the final, and wins the title.
  await win(adminApi, await readEncounter(adminApi, semi.id), s(4));
  model.decide(s(1), s(4), s(4));
  await playBracket(adminApi, seed.tournament.id, seed.stage.id, model, (h, a) => (h === s(4) || a === s(4) ? s(4) : better(h, a)));
  const rows = await expectPlacements(adminApi, seed.tournament.id, seed.stage.id, seeds, model);
  expect([s(4), s(2), s(1), s(3)].map((t) => rowOf(rows, t).position)).toEqual([1, 2, 3, 3]);
});

test("ffa: two lobbies scored by a placement table; ties go to game wins, the headline column, then the last place; the top 2 of each seed the playoff", async ({
  adminApi,
}) => {
  test.setTimeout(600_000);
  const ws = await createWorkspace(adminApi);
  const tournament = await createTournament(adminApi, ws.id);
  const teams = await seedTeams(adminApi, tournament.id, 8, { players: false });
  const placementPoints = [10, 6, 3, 1];
  const ffa = await createStage(
    adminApi,
    tournament.id,
    teams.map((t) => t.id),
    {
      stageType: "ffa_league",
      groups: 2,
      bestOf: 2,
      extra: {
        advance_count: 2,
        scoring: { preset: "points", columns: [{ key: "kills", label: "Kills" }], placement_points: placementPoints, formula: "place_pts" },
      },
    }
  );
  await generateStage(adminApi, ffa.id);
  const playoff = await adminApi.post<Stage>(
    `/api/v1/admin/stages/tournament/${tournament.id}`,
    { name: "Playoffs", stage_type: "single_elimination", best_of: { default: 1 }, order: 1 },
    201
  );
  await adminApi.post(`/api/v1/admin/stages/${playoff.id}/items`, { name: "Bracket", type: "single_bracket", order: 0 }, 201);
  await setStatus(adminApi, tournament.id, "live", true);

  const stage = await adminApi.get<Stage>(`/api/v1/admin/stages/${ffa.id}`);
  const [itemA, itemB] = [...stage.items].sort((x, y) => x.id - y.id).map((item) => item.id);
  const [p1, p2, p3, p4] = seedOrder(stage, 0);
  const [q1, q2, q3, q4] = seedOrder(stage, 1);
  const lobbies = await listEncounters(adminApi, tournament.id, ffa.id, 4);
  const lobbyOf = (team: number) => lobbies.find((l) => l.teams.some((t) => t.team_id === team))!;
  expect(lobbyOf(p1).id, "group A plays one lobby").toBe(lobbyOf(p4).id);
  expect(lobbyOf(q1).id, "group B plays another").not.toBe(lobbyOf(p1).id);

  type Line = [team: number, place: number, kills: number];
  const post = (lobby: number, position: number, lines: { team_id: number; placement?: number; stats: { kills: number } }[]) =>
    adminApi.raw("POST", `/api/v1/admin/encounters/${lobby}/ffa/games/${position}/results`, { body: { results: lines } });
  const game = async (position: number, lines: Line[]) => {
    const res = await post(lobbyOf(lines[0][0]).id, position, lines.map(([team_id, placement, kills]) => ({ team_id, placement, stats: { kills } })));
    expect(res.status(), `game ${position}: ${await res.text()}`).toBe(200);
  };
  // The formula reads the place: every place, each exactly once.
  const unplaced = await post(lobbyOf(p1).id, 1, [p1, p2, p3, p4].map((team_id) => ({ team_id, stats: { kills: 1 } })));
  expect(await unplaced.text(), "places are required").toContain("ffa_result_placement_required");
  const twice = await post(lobbyOf(p1).id, 1, [p1, p2, p3, p4].map((team_id, i) => ({ team_id, placement: i < 2 ? 1 : i + 1, stats: { kills: 1 } })));
  expect(await twice.text(), "a place taken twice is refused").toContain("ffa_result_invalid_placement");

  const games: Record<"A" | "B", Line[][]> = {
    // p1 and p2: 16 points and one win each, p2 has more kills; p3 and p4: 4 points, equal kills, p4 placed better last.
    A: [
      [[p1, 1, 5], [p2, 2, 8], [p3, 3, 2], [p4, 4, 3]],
      [[p2, 1, 4], [p1, 2, 5], [p4, 3, 1], [p3, 4, 2]],
    ],
    // q4 wins both; q3 and q1 on 7 points with no win, q3 has the kill.
    B: [
      [[q4, 1, 1], [q3, 2, 1], [q2, 3, 0], [q1, 4, 0]],
      [[q4, 1, 0], [q1, 2, 0], [q2, 3, 0], [q3, 4, 0]],
    ],
  };
  for (const group of ["A", "B"] as const) for (const [i, lines] of games[group].entries()) await game(i + 1, lines);

  /** The documented ffa_default order: points, game wins, the stage's first column, the last place; the id last. */
  const ffaTable = (lobby: Line[][]) => {
    const rows = new Map<number, { team: number; points: number; wins: number; kills: number; last: number }>();
    for (const lines of lobby) {
      for (const [team, place, kills] of lines) {
        const row = rows.get(team) ?? { team, points: 0, wins: 0, kills: 0, last: 0 };
        row.points += placementPoints[place - 1] ?? 0;
        row.wins += place === 1 ? 1 : 0;
        row.kills += kills;
        row.last = place;
        rows.set(team, row);
      }
    }
    return [...rows.values()].sort((x, y) => y.points - x.points || y.wins - x.wins || y.kills - x.kills || x.last - y.last || x.team - y.team);
  };
  const expectedA = ffaTable(games.A);
  const expectedB = ffaTable(games.B);
  expect(expectedA.map((r) => r.team), "hand-derived lobby A").toEqual([p2, p1, p4, p3]);
  expect(expectedB.map((r) => r.team), "hand-derived lobby B").toEqual([q4, q3, q1, q2]);

  const rows = await stageStandings(adminApi, tournament.id, ffa.id);
  for (const [item, expected] of [
    [itemA, expectedA],
    [itemB, expectedB],
  ] as const) {
    expect(
      rows.filter((r) => r.stage_item_id === item).map((r) => [r.team_id, r.position, r.points, r.win, r.matches]),
      `lobby table of stage item ${item}`
    ).toEqual(expected.map((r, i) => [r.team, i + 1, r.points, r.wins, 2]));
  }
  expect((await adminApi.get<Stage>(`/api/v1/admin/stages/${ffa.id}`)).is_completed, "both lobbies played their card").toBe(true);

  await generateStage(adminApi, playoff.id);
  const firstRound = (await listEncounters(adminApi, tournament.id, playoff.id)).filter((e) => e.round === 1).map((e) => seats(e).join("-"));
  expect(firstRound.sort(), "A1 vs B2, B1 vs A2").toEqual([`${p2}-${q3}`, `${q4}-${p1}`].sort());
});
