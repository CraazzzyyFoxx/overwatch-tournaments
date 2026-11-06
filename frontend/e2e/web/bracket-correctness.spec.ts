import type { Locator, Page } from "@playwright/test";
import {
  doubleElimination,
  enter,
  ladder,
  playBracket,
  seedGroupsToPlayoffs,
  seedOrder,
  singleElimination,
  startPlayoff,
  stageStandings,
  type TableStanding,
} from "../support/correctness";
import { expect, openPage, test } from "../support/fixtures";
import { listEncounters, seedBracket, type Encounter, type Stage } from "../support/flows";

/**
 * The public bracket pages against the engine: every card shows the teams and
 * score the encounter holds, every standings table the API's order. The
 * tournaments are played to the end through the organizer API first.
 */

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** The better seed always wins. */
const better = (seeds: number[]) => (home: number, away: number) => (seeds.indexOf(home) < seeds.indexOf(away) ? home : away);

/** Each card renders its seats as "<team> <score>", slot order. */
async function expectCards(page: Page, encounters: Encounter[]) {
  await expect(page.locator("[data-match-id]"), "one card per encounter").toHaveCount(encounters.length);
  for (const e of encounters) {
    const card = page.locator(`[data-match-id="${e.id}"]`);
    for (const seat of [...e.teams].sort((a, b) => a.slot - b.slot)) {
      await expect(card, `card ${e.id}: ${seat.name} ${seat.score}`).toContainText(new RegExp(`${escape(seat.name)}\\s*${seat.score}`));
    }
  }
}

/**
 * A standings table in the API's order: the rank column, the record and (group
 * tables) the points of every row. Rows sharing a rank may come in either order,
 * so only an unshared rank pins its team to the row.
 */
async function expectTable(table: Locator, rows: TableStanding[], names: Map<number, string>, opts: { groups: boolean }) {
  const rank = (row: TableStanding) => (opts.groups ? row.position : row.overall_position);
  const sorted = [...rows].sort((a, b) => rank(a) - rank(b));
  // Cut lines ("top 2 advance") are rows of a single cell.
  const trs = table.locator("tbody tr").filter({ hasNot: table.page().locator("td.st-cut") });
  await expect(trs).toHaveCount(rows.length);
  for (const [i, row] of sorted.entries()) {
    const cells = trs.nth(i).locator("td");
    await expect(cells.nth(0), `row ${i + 1} rank`).toHaveText(String(rank(row)));
    if (sorted.filter((other) => rank(other) === rank(row)).length > 1) continue;
    await expect(cells.nth(1), `row ${i + 1} team`).toContainText(names.get(row.team_id)!);
    await expect(cells.nth(2), `row ${i + 1} record`).toHaveText(`${row.win}·${row.draw}·${row.lose}`);
    if (opts.groups) await expect(cells.nth(3), `row ${i + 1} points`).toHaveText(row.points.toFixed(1));
  }
  for (const row of rows) await expect(trs.filter({ hasText: names.get(row.team_id)! }), `${names.get(row.team_id)} is listed once`).toHaveCount(1);
}

const standingsTables = (page: Page) => page.getByRole("region", { name: /Tournament standings/ });

test("completed double elimination: every card shows its two teams and score; the standings tab ranks as the API", async ({ page, adminApi }) => {
  const seed = await seedBracket(adminApi, { teams: 6, stageType: "double_elimination", bestOf: 1, players: false });
  const seeds = seedOrder(seed.stage);
  const encounters = await playBracket(adminApi, seed.tournament.id, seed.stage.id, doubleElimination(seeds), better(seeds));
  const rows = await stageStandings(adminApi, seed.tournament.id, seed.stage.id);
  const names = new Map(seed.teams.map((t) => [t.id, t.name]));
  const url = `/tournaments/${seed.tournament.slug}/bracket?stage=${seed.stage.id}`;

  await openPage(page, url);
  await expectCards(page, encounters);
  await openPage(page, `${url}&view=standings`);
  await expect(standingsTables(page)).toHaveCount(1);
  await expectTable(standingsTables(page), rows, names, { groups: false });
});

test("groups → playoffs: group cards and tables, then the playoff bracket and its table, as the API has them", async ({ page, adminApi }) => {
  test.setTimeout(600_000);
  const setup = await seedGroupsToPlayoffs(adminApi);
  const { tournament, groupStage, playoff } = setup;
  for (const r of [...ladder(setup.groupA), ...ladder(setup.groupB)]) await enter(adminApi, setup.encounters, r);
  await stageStandings(adminApi, tournament.id, groupStage.id);
  await startPlayoff(adminApi, tournament.id, setup.filterNodeId, playoff);
  const seeds = seedOrder(await adminApi.get<Stage>(`/api/v1/admin/stages/${playoff.id}`));
  const playoffEncounters = await playBracket(adminApi, tournament.id, playoff.id, singleElimination(seeds), better(seeds));
  const groupEncounters = await listEncounters(adminApi, tournament.id, groupStage.id);
  const groupRows = await stageStandings(adminApi, tournament.id, groupStage.id);
  const playoffRows = await stageStandings(adminApi, tournament.id, playoff.id);
  const names = new Map(setup.teams.map((t) => [t.id, t.name]));
  const base = `/tournaments/${tournament.slug}/bracket`;

  await openPage(page, `${base}?stage=${groupStage.id}`);
  await expectCards(page, groupEncounters);
  await openPage(page, `${base}?stage=${groupStage.id}&view=standings`);
  await expect(standingsTables(page), "one table per group").toHaveCount(2);
  const items = [...groupStage.items].sort((a, b) => a.id - b.id);
  for (const [i, item] of items.entries()) {
    await expectTable(
      standingsTables(page).nth(i),
      groupRows.filter((r) => r.stage_item_id === item.id),
      names,
      { groups: true }
    );
  }

  await openPage(page, `${base}?stage=${playoff.id}`);
  await expectCards(page, playoffEncounters);
  await openPage(page, `${base}?stage=${playoff.id}&view=standings`);
  await expectTable(standingsTables(page), playoffRows, names, { groups: false });
});

test("double elimination on a phone: every round's list names both teams with their score @mobile", async ({ page, adminApi, isMobile }) => {
  test.skip(!isMobile, "the round-by-round list is the phone layout");
  const seed = await seedBracket(adminApi, { teams: 4, stageType: "double_elimination", bestOf: 1, players: false });
  const seeds = seedOrder(seed.stage);
  const encounters = await playBracket(adminApi, seed.tournament.id, seed.stage.id, doubleElimination(seeds), better(seeds));
  await openPage(page, `/tournaments/${seed.tournament.slug}/bracket?stage=${seed.stage.id}`);

  // Chips run the upper rounds up, then the lower rounds down (-1, -2, ...).
  const rounds = [...new Set(encounters.map((e) => e.round))].sort((a, b) => (a > 0 && b > 0 ? a - b : a > 0 ? -1 : b > 0 ? 1 : b - a));
  const chips = page.getByRole("group", { name: /Bracket — scroll horizontally/ }).getByRole("button");
  await expect(chips, "one chip per round").toHaveCount(rounds.length);
  for (const [i, round] of rounds.entries()) {
    await chips.nth(i).click();
    await expect(chips.nth(i)).toHaveAttribute("aria-pressed", "true");
    for (const e of encounters.filter((x) => x.round === round)) {
      const item = page.locator(`a[href="/encounters/${e.id}"]`);
      for (const seat of e.teams) await expect(item, `round ${round}: ${seat.name} ${seat.score}`).toContainText(new RegExp(`${escape(seat.name)}\\s*${seat.score}`));
    }
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "the bracket does not scroll the page sideways").toBeLessThanOrEqual(1);
});
