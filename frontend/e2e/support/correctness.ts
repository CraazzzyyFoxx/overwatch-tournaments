import { expect } from "@playwright/test";
import type { Api } from "./api";
import {
  createStage,
  formTeams,
  startStage,
  listEncounters,
  seedTeams,
  setResult,
  waitForJob,
  type Encounter,
  type Stage,
  type StandingRow,
  type TournamentJob,
} from "./flows";
import { setPoints } from "./results";
import { nodeNamed, waitNode, type AdminFlow } from "./flow";
import { createTournament, createWorkspace } from "./seed";

/**
 * Reference models for the tournament-correctness specs. Every expectation is
 * computed here from the results a test enters and the rules the engine
 * documents (docs/business-logic-inventory.md §7-8, the generators' docstrings),
 * never read back from the API it is compared with.
 */

// ---------------------------------------------------------------- reading the API

/** A stage item's teams in slot order: the engine's seed order under the default `seed_ranking: slot`. */
export function seedOrder(stage: Stage, itemIndex = 0): number[] {
  const item = [...stage.items].sort((a, b) => a.id - b.id)[itemIndex];
  return [...item.inputs].sort((a, b) => a.slot - b.slot).map((input) => input.team_id!);
}

/** `[slot 1, slot 2]` team ids of a duel; an empty seat is `null`. */
export function seats(encounter: Pick<Encounter, "teams">): [number | null, number | null] {
  const at = (slot: number) => encounter.teams.find((t) => t.slot === slot && t.team_id != null)?.team_id ?? null;
  return [at(1), at(2)];
}

/** Organizer result in which `winner` takes the series `won`:`lost`, whatever slot it sits in. */
export async function win(api: Api, encounter: Pick<Encounter, "id" | "teams">, winner: number, won = 1, lost = 0) {
  const [home, away] = seats(encounter);
  expect([home, away], `encounter ${encounter.id} seats the winner ${winner}`).toContain(winner);
  expect(home !== null && away !== null, `encounter ${encounter.id} has both seats filled`).toBe(true);
  return setResult(api, encounter, home === winner ? [won, lost] : [lost, won]);
}

/** Every encounter of a stage that seats a team, as `round:home-away` (`-` = empty seat), sorted. */
export function bracketState(encounters: Pick<Encounter, "round" | "teams">[]): string[] {
  return encounters
    .map((e) => ({ round: e.round, s: seats(e) }))
    .filter(({ s }) => s[0] !== null || s[1] !== null)
    .map(({ round, s }) => `${round}:${s[0] ?? "-"}-${s[1] ?? "-"}`)
    .sort();
}

/** The standing columns the tiebreakers write, beyond flows.ts's `StandingRow`. */
export type TableStanding = StandingRow & {
  /** Median Buchholz (the engine stores the trimmed sum here). */
  buchholz: number | null;
  full_buchholz: number | null;
  /** Head-to-head wins inside the team's points bucket. */
  tb: number | null;
  score_differential: number | null;
  tie_group: number | null;
};

/** Recalculates and returns one stage's rows. Tournament-wide recalculation, stage-filtered read. */
export async function stageStandings(api: Api, tournamentId: number, stageId: number): Promise<TableStanding[]> {
  await waitForJob(api, await api.post<TournamentJob>(`/api/v1/admin/standings/recalculate/${tournamentId}`, undefined, 202));
  const rows = await api.get<TableStanding[]>(`/api/v1/tournaments/${tournamentId}/standings`);
  return rows.filter((r) => r.stage_id === stageId).sort((a, b) => a.stage_item_id - b.stage_item_id || a.position - b.position);
}

export function rowOf<T extends StandingRow>(rows: T[], teamId: number): T {
  const row = rows.find((r) => r.team_id === teamId);
  expect(row, `standing row for team ${teamId}`).toBeTruthy();
  return row!;
}

/** The duel seating both teams, in either slot order. */
export function encounterOf<T extends Pick<Encounter, "teams">>(encounters: T[], a: number, b: number): T {
  const found = encounters.find((e) => pairKey(...seats(e)) === pairKey(a, b));
  expect(found, `an encounter between ${a} and ${b}`).toBeTruthy();
  return found!;
}

/** Organizer result `home` hs : as `away`, oriented onto the encounter's slots. */
export async function enter(api: Api, encounters: Pick<Encounter, "id" | "teams">[], r: Result) {
  const encounter = encounterOf(encounters, r.home, r.away);
  return setResult(api, encounter, seats(encounter)[0] === r.home ? [r.hs, r.as] : [r.as, r.hs]);
}

/**
 * Standard 1-vs-N bracket order: seed 1 meets seed N, seed N/2 meets N/2+1, and
 * the two top seeds can only meet in the final. For 8: 1-8, 4-5, 2-7, 3-6.
 * Values are 0-based seed indices.
 */
export function standardOrder(size: number): number[] {
  if (size === 1) return [0];
  return standardOrder(size / 2).flatMap((seed) => [seed, size - 1 - seed]);
}

export type Src = { team: number } | { winnerOf: number } | { loserOf: number };
export type ModelMatch = { id: number; round: number; slots: [Src | null, Src | null]; winner?: number; loser?: number };

/**
 * An elimination bracket as a graph of origins: a seat is a seeded team, or
 * the winner / loser of an earlier match. A pairing with one origin missing is
 * a bye -- no match is created and the origin passes straight on.
 */
export class BracketModel {
  readonly matches: ModelMatch[] = [];

  /** `grandFinalRound`: a double elimination's Grand Final round; `null` for single elimination. */
  constructor(readonly grandFinalRound: number | null) {}

  play(a: Src | null, b: Src | null, round: number, force = false): { winner: Src | null; loser: Src | null } {
    if ((a === null || b === null) && !force) return { winner: a ?? b, loser: null };
    const id = this.matches.length;
    this.matches.push({ id, round, slots: [a, b] });
    return { winner: { winnerOf: id }, loser: { loserOf: id } };
  }

  pairUp(origins: (Src | null)[], round: number) {
    const winners: (Src | null)[] = [];
    const losers: (Src | null)[] = [];
    for (let i = 0; i < origins.length; i += 2) {
      const { winner, loser } = this.play(origins[i], origins[i + 1] ?? null, round);
      winners.push(winner);
      losers.push(loser);
    }
    return { winners, losers };
  }

  team(src: Src | null): number | null {
    if (src === null) return null;
    if ("team" in src) return src.team;
    const m = this.matches[("winnerOf" in src ? src.winnerOf : src.loserOf)];
    return ("winnerOf" in src ? m.winner : m.loser) ?? null;
  }

  seatsOf(m: ModelMatch): [number | null, number | null] {
    return [this.team(m.slots[0]), this.team(m.slots[1])];
  }

  /** Same shape as `bracketState`, so the two compare directly. */
  state(): string[] {
    return this.matches
      .map((m) => ({ round: m.round, s: this.seatsOf(m) }))
      .filter(({ s }) => s[0] !== null || s[1] !== null)
      .map(({ round, s }) => `${round}:${s[0] ?? "-"}-${s[1] ?? "-"}`)
      .sort();
  }

  /** Both seats known, no result yet. */
  ready(): ModelMatch[] {
    return this.matches.filter((m) => m.winner === undefined && this.seatsOf(m).every((t) => t !== null));
  }

  decide(home: number, away: number, winner: number) {
    const m = this.ready().find((x) => {
      const [a, b] = this.seatsOf(x);
      return a === home && b === away;
    });
    if (!m) throw new Error(`model has no open match ${home}-${away}`);
    m.winner = winner;
    m.loser = winner === home ? away : home;
    return m;
  }

  undo(m: ModelMatch) {
    // Unwinding a result empties every seat it filled, recursively: the model
    // re-derives seats from origins, so clearing the decided teams is enough.
    const clear = (id: number) => {
      const target = this.matches[id];
      target.winner = undefined;
      target.loser = undefined;
      for (const next of this.matches) {
        if (next.slots.some((s) => s && !("team" in s) && ("winnerOf" in s ? s.winnerOf : s.loserOf) === id) && next.winner !== undefined) {
          clear(next.id);
        }
      }
    };
    clear(m.id);
  }

  /** When a loss happened, for the loss that eliminated a team (its latest). */
  private eliminationKey(round: number) {
    if (this.grandFinalRound === null) return round;
    // Double elimination: an upper loss before the Grand Final only drops a
    // team; lower rounds (-1, -2, ...) are chronological by depth and all of
    // them precede the Grand Final (and its Reset).
    if (round < 0) return -round;
    return round < this.grandFinalRound ? 0 : 10_000 + round;
  }

  /**
   * Places by competition ranking over elimination time: the losers of one
   * round share the best place below every team that lasted longer. A team
   * still in it -- seated in an undecided match, or the winner of the bracket's
   * last match -- outranks every eliminated one (the engine shows it as 0).
   */
  placements(): Map<number, number> {
    const key = new Map<number, number>();
    for (const m of this.matches) {
      if (m.winner === undefined) continue;
      const k = this.eliminationKey(m.round);
      if ((key.get(m.loser!) ?? -Infinity) < k) key.set(m.loser!, k);
    }
    const final = this.matches.reduce((a, b) => (this.eliminationKey(b.round) >= this.eliminationKey(a.round) ? b : a));
    const alive = this.matches.filter((m) => m.winner === undefined).flatMap((m) => this.seatsOf(m));
    for (const team of [...alive, final.winner]) if (team != null) key.set(team, Infinity);
    const out = new Map<number, number>();
    for (const [teamId, k] of key) out.set(teamId, 1 + [...key.values()].filter((other) => other > k).length);
    return out;
  }

  record(teamId: number): { win: number; lose: number } {
    const decided = this.matches.filter((m) => m.winner !== undefined);
    return {
      win: decided.filter((m) => m.winner === teamId).length,
      lose: decided.filter((m) => m.loser === teamId).length,
    };
  }
}

/** Single elimination over `seeds` (seed 1 first): power-of-two field, byes to the top seeds. */
export function singleElimination(seeds: number[]): BracketModel {
  const model = new BracketModel(null);
  const size = 2 ** Math.ceil(Math.log2(seeds.length));
  let slots: (Src | null)[] = standardOrder(size).map((i) => (i < seeds.length ? { team: seeds[i] } : null));
  for (let round = 1; slots.length > 1; round++) slots = model.pairUp(slots, round).winners;
  return model;
}

/**
 * Double elimination as `double_elimination.generate` documents it: the upper
 * bracket is a single elimination; lower round 1 pairs the upper round-1
 * losers two by two; each later upper round's losers drop in REVERSED order
 * (slot 2) against the lower survivors (slot 1), followed by a round that
 * halves the survivors; the Grand Final seats the upper champion in slot 1 and
 * the lower champion in slot 2. Lower round numbers are -1, -2, ... in that
 * order, a round with no match still taking its number.
 */
export function doubleElimination(seeds: number[]): BracketModel {
  const size = 2 ** Math.ceil(Math.log2(seeds.length));
  const upperRounds = Math.log2(size);
  const model = new BracketModel(upperRounds + 1);
  let slots: (Src | null)[] = standardOrder(size).map((i) => (i < seeds.length ? { team: seeds[i] } : null));
  const upperLosers: (Src | null)[][] = [];
  for (let round = 1; round <= upperRounds; round++) {
    const played = model.pairUp(slots, round);
    slots = played.winners;
    upperLosers.push(played.losers);
  }
  let lower = 1;
  let carry = model.pairUp(upperLosers[0], -lower).winners;
  lower++;
  for (let round = 2; round <= upperRounds; round++) {
    const dropouts = [...upperLosers[round - 1]].reverse();
    carry = dropouts.map((dropout, k) => model.play(carry[k] ?? null, dropout, -lower).winner);
    lower++;
    if (carry.length > 1) {
      carry = model.pairUp(carry, -lower).winners;
      lower++;
    }
  }
  model.play(slots[0], carry[carry.length - 1], upperRounds + 1, true);
  return model;
}

/**
 * Plays an elimination stage through the organizer API, asserting before every
 * result that the persisted bracket equals the model's. `pick(home, away, round)`
 * names each winner; `limit` stops after that many results; `after` sees each
 * decided model match (to add what the engine materialises lazily: a Reset).
 */
export async function playBracket(
  api: Api,
  tournamentId: number,
  stageId: number,
  model: BracketModel,
  pick: (home: number, away: number, round: number) => number,
  opts: { limit?: number; after?: (m: ModelMatch) => void } = {}
): Promise<Encounter[]> {
  for (let played = 0; ; played++) {
    // Advancement is part of the result write, but read through a poll: a
    // regression that made it lag would otherwise read as a wrong seat.
    let live: Encounter[] = [];
    await expect
      .poll(async () => bracketState((live = await listEncounters(api, tournamentId, stageId))), {
        message: `persisted bracket equals the model after ${played} results`,
      })
      .toEqual(model.state());
    const open = model.ready();
    if (!open.length || played >= (opts.limit ?? Infinity)) return live;
    const m = open[0];
    const [home, away] = model.seatsOf(m) as [number, number];
    const encounter = live.find((e) => e.round === m.round && seats(e)[0] === home && seats(e)[1] === away)!;
    const winner = pick(home, away, m.round);
    await win(api, encounter, winner);
    // Not inside `opts.after?.(…)`: an optional call skips evaluating its argument.
    const decided = model.decide(home, away, winner);
    opts.after?.(decided);
  }
}

// ---------------------------------------------------------------- group tables

export type Result = { home: number; away: number; hs: number; as: number };
export type Points = { win: number; draw: number; loss: number };

/** `winner` beats `loser` 1:0. */
export function beat(winner: number, loser: number): Result {
  return { home: winner, away: loser, hs: 1, as: 0 };
}

/** A group's results where the 1st beats everyone, the 2nd the 3rd and 4th, the 3rd the 4th. */
export function ladder([p1, p2, p3, p4]: number[]): Result[] {
  return [beat(p1, p2), beat(p1, p3), beat(p1, p4), beat(p2, p3), beat(p2, p4), beat(p3, p4)];
}

/**
 * Groups → a `per_item_top` filter → playoff, wired in one graph save (`PUT /admin/tournaments/{id}/flow`): the
 * filter passes the top `top` of every group, and the playoff is seated from it once the filter is `final`.
 * Returns the filter's node id.
 */
export async function wireGroupsToPlayoff(
  api: Api,
  tournamentId: number,
  groups: Pick<Stage, "node_id">,
  playoff: Pick<Stage, "node_id">,
  top = 2
): Promise<number> {
  const name = `Top ${top} per group`;
  const flow = await api.put<AdminFlow>(`/api/v1/admin/tournaments/${tournamentId}/flow`, {
    nodes: [{ ref: "cut", kind: "filter", name, config: { mode: "per_item_top", n: top } }],
    edges: [
      { source: groups.node_id, source_port: "ranking", target: "cut", target_port: "ranking" },
      { source: "cut", source_port: "passed", target: playoff.node_id, target_port: "participants" },
    ],
  });
  return nodeNamed(flow, "filter", name).id;
}

/** The playoff stage fed by the filter: waits for the groups to close (the filter `final`), then seats it (`ready`) and starts it. */
export async function startPlayoff(api: Api, tournamentId: number, filterNodeId: number, playoff: Pick<Stage, "node_id">) {
  await waitNode(api, tournamentId, filterNodeId, "final");
  await startStage(api, playoff);
}

/**
 * A tournament that derives `live` (win/draw/loss 3/1/0) with 8 teams in a generated
 * two-group round robin, and an unseeded single elimination playoff after it, wired by
 * a `per_item_top` filter (top 2 of each group) with `cross` seeding.
 */
export async function seedGroupsToPlayoffs(api: Api) {
  const workspace = await createWorkspace(api);
  const tournament = await createTournament(api, workspace.id);
  const teams = await seedTeams(api, tournament.id, 8, { players: false });
  await formTeams(api, tournament.id);
  const created = await createStage(
    api,
    tournament.id,
    teams.map((t) => t.id),
    { stageType: "round_robin", groups: 2, bestOf: 1 }
  );
  await setPoints(api, created.id, 3, 1, 0);
  await startStage(api, created);
  const playoff = await api.post<Stage>(
    `/api/v1/admin/stages/tournament/${tournament.id}`,
    { name: "Playoffs", stage_type: "single_elimination", best_of: { default: 1 }, order: 1, seed_ranking: "cross" },
    201
  );
  await api.post(`/api/v1/admin/stages/${playoff.id}/items`, { name: "Bracket", type: "single_bracket", order: 0 }, 201);
  const filterNodeId = await wireGroupsToPlayoff(api, tournament.id, created, playoff);
  const groupStage = await api.get<Stage>(`/api/v1/admin/stages/${created.id}`);
  return {
    tournament,
    teams,
    groupStage,
    playoff,
    filterNodeId,
    groupA: seedOrder(groupStage, 0),
    groupB: seedOrder(groupStage, 1),
    encounters: await listEncounters(api, tournament.id, groupStage.id),
  };
}

export type TableRow = {
  team: number;
  matches: number;
  win: number;
  draw: number;
  lose: number;
  points: number;
  score_differential: number;
  buchholz: number;
  median_buchholz: number;
  head_to_head: number;
};

/**
 * A group table by the documented metrics: W/D/L by the result, points by the
 * win/draw/loss values (+ bye points), score differential summed over the
 * series scores, Buchholz = the sum of the opponents' points, median Buchholz
 * = the same without the best and worst opponent once there are more than two,
 * head-to-head = wins against teams level on points. Sorted lexicographically
 * by `order` (descending), the team id last.
 */
export function groupTable(
  teams: number[],
  results: Result[],
  points: Points,
  order: string[],
  byes: Map<number, number> = new Map(),
  byePoints = points.win
): TableRow[] {
  const rows = new Map<number, TableRow & { opponents: number[] }>(
    teams.map((team) => [
      team,
      { team, matches: 0, win: 0, draw: 0, lose: 0, points: 0, score_differential: 0, buchholz: 0, median_buchholz: 0, head_to_head: 0, opponents: [] },
    ])
  );
  for (const r of results) {
    for (const [me, other, mine, theirs] of [
      [r.home, r.away, r.hs, r.as],
      [r.away, r.home, r.as, r.hs],
    ]) {
      const row = rows.get(me)!;
      row.matches++;
      row.opponents.push(other);
      row.score_differential += mine - theirs;
      if (mine > theirs) (row.win++, (row.points += points.win));
      else if (mine === theirs) (row.draw++, (row.points += points.draw));
      else (row.lose++, (row.points += points.loss));
    }
  }
  for (const [team, count] of byes) rows.get(team)!.points += count * byePoints;
  for (const row of rows.values()) {
    const opp = row.opponents.map((o) => rows.get(o)!.points);
    row.buchholz = opp.reduce((a, b) => a + b, 0);
    const sorted = [...opp].sort((a, b) => a - b);
    row.median_buchholz = (opp.length > 2 ? sorted.slice(1, -1) : sorted).reduce((a, b) => a + b, 0);
  }
  for (const r of results) {
    const home = rows.get(r.home)!;
    const away = rows.get(r.away)!;
    if (home.points !== away.points || r.hs === r.as) continue;
    (r.hs > r.as ? home : away).head_to_head++;
  }
  const metric = (row: TableRow, name: string): number => {
    switch (name) {
      case "points":
        return row.points;
      case "match_wins":
        return row.win;
      case "head_to_head":
        return row.head_to_head;
      case "buchholz":
        return Math.round(row.buchholz * 10) / 10;
      case "median_buchholz":
        return Math.round(row.median_buchholz * 10) / 10;
      case "score_differential":
      case "map_differential":
        return row.score_differential;
      default:
        throw new Error(`unknown metric ${name}`);
    }
  };
  return [...rows.values()]
    .map(({ opponents: _, ...row }) => row)
    .sort((a, b) => {
      for (const name of order) {
        const d = metric(b, name) - metric(a, name);
        if (d !== 0) return d;
      }
      return a.team - b.team;
    });
}

/** Every pair of `teams`, as sorted `a-b` keys. */
export function allPairs(teams: number[]): string[] {
  const out: string[] = [];
  for (let i = 0; i < teams.length; i++) for (let j = i + 1; j < teams.length; j++) out.push(pairKey(teams[i], teams[j]));
  return out.sort();
}

export function pairKey(a: number | null, b: number | null) {
  return [a, b].sort((x, y) => Number(x) - Number(y)).join("-");
}

/** Every way to pair all of `teams` without a rematch (an even field: 8 teams have at most 105). */
export function pairings(teams: number[], played: Set<string>): [number, number][][] {
  if (!teams.length) return [[]];
  const [first, ...rest] = teams;
  return rest.flatMap((other, i) =>
    played.has(pairKey(first, other)) ? [] : pairings(rest.filter((_, j) => j !== i), played).map((p) => [[first, other] as [number, number], ...p])
  );
}
