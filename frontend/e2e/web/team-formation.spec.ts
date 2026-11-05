import type { Page } from "@playwright/test";
import { BASE_URL } from "../support/env";
import { expect, openPage, test } from "../support/fixtures";
import { listTeams, openRegistration, seedPlayers } from "../support/flows";
import { createTournament, createWorkspace, nodeOf, transitionNode } from "../support/seed";
import { createMix, draftBoard, pickFirstSafe, seedDraft, seedMembers, type DraftBoard, type Mix } from "../support/team-formation";

// Team formation through the UI: the live draft room (two captains in their
// own browser contexts, realtime), the admin draft dashboard, the tournament
// balancer entry, the pickup-mix board and the rank overview.

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** The captain picks an available player through the pool card and its confirm dialog; returns the tag. */
async function pickFromPool(page: Page, board: DraftBoard) {
  const player = board.players.find((p) => p.status === "available")!;
  const tag = player.identity!.handle;
  const role = player.primary_role!.role;
  await page.getByRole("button", { name: `Select ${tag} as ${role[0].toUpperCase()}${role.slice(1)}`, exact: true }).first().click();
  await page.getByRole("dialog", { name: tag }).getByRole("button", { name: `Pick ${tag} as ${role}`, exact: true }).click();
  return tag;
}

const rosterSeat = (page: Page, tag: string) =>
  page.getByRole("list", { name: "Team rosters" }).getByRole("button", { name: new RegExp(`^${escapeRe(tag)} · `) });

test("live draft: admin starts it, each captain sees the other's pick without reloading", async ({ adminApi, makeUser, page, pageAs }) => {
  const d = await seedDraft(adminApi, makeUser);
  await openPage(page, `/admin/tournaments/${d.tournament.id}/teams/draft`);
  await expect(page.getByRole("heading", { name: "Ready to start" })).toBeVisible();
  await page.getByRole("button", { name: "Start draft" }).click();
  await page.getByRole("alertdialog").or(page.getByRole("dialog")).getByRole("button", { name: "Start draft" }).click();
  await expect.poll(async () => (await draftBoard(adminApi, d.session.id)).session.status, { message: "dashboard Start draft starts the session" }).toBe("live");

  const [cap1, cap2] = [await pageAs(d.captains[0]), await pageAs(d.captains[1])];
  for (const cap of [cap1, cap2]) {
    await openPage(cap, `/draft/${d.tournament.id}`);
    // The fixed cookie banner covers the bottom of the pool on first visit.
    await cap.getByRole("button", { name: "Decline analytics" }).click();
  }
  await expect(cap1.getByText("Pick 1: your turn.")).toBeVisible();
  await expect(cap2.getByText("Pick 1: your turn.")).toHaveCount(0);

  const first = await pickFromPool(cap1, await draftBoard(adminApi, d.session.id));
  await expect.poll(async () => (await draftBoard(adminApi, d.session.id)).picks[0].status).toBe("completed");
  // Realtime: captain 2's room moves on and seats captain 1's pick with no reload.
  await expect(cap2.getByText("Pick 2: your turn."), "captain 2 is told it is their turn").toBeVisible();
  await expect(rosterSeat(cap2, first), "captain 1's pick appears in captain 2's roster view").toBeVisible();
  await expect(cap2.getByRole("tab", { name: "Available 7" })).toBeVisible();

  const second = await pickFromPool(cap2, await draftBoard(adminApi, d.session.id));
  await expect(rosterSeat(cap1, second), "captain 2's pick appears in captain 1's roster view").toBeVisible();
  await expect(cap1.getByRole("tab", { name: "Available 6" })).toBeVisible();
  // The admin dashboard follows the same session.
  await expect.poll(async () => (await draftBoard(adminApi, d.session.id)).current_pick?.overall_no).toBe(3);
  await adminApi.post(`${d.lifecycle}/cancel`);
});

test("@mobile a spectator follows a live draft on a phone", async ({ adminApi, makeUser, page }) => {
  const d = await seedDraft(adminApi, makeUser, { start: true });
  await openPage(page, `/draft/${d.tournament.id}`);
  await expect(page.getByRole("heading", { name: "Draft", level: 1 })).toBeVisible();
  await expect(page.getByRole("timer")).toBeVisible();
  const board = await draftBoard(adminApi, d.session.id);
  const safe = await pickFirstSafe(d.captains[0].api, board.current_pick!.id);
  const tag = board.players.find((p) => p.id === safe.player_id)!.identity!.handle;
  await expect(page.getByRole("button", { name: new RegExp(`^Select ${escapeRe(tag)} as`) }), "the drafted player leaves the pool live").toHaveCount(0);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "no horizontal scroll on a phone").toBeLessThanOrEqual(1);
});

test("roster tab opens the tournament balancer with the registration pool", async ({ adminApi, page }) => {
  const ws = await createWorkspace(adminApi);
  const t = await createTournament(adminApi, ws.id);
  const { registrationNodeId } = await openRegistration(adminApi, t.id);
  const pool = await seedPlayers(adminApi, t.id, 10, { registrationNodeId });
  // The balancer works on a closed intake and a forming formation.
  await transitionNode(adminApi, registrationNodeId, "closed");
  await transitionNode(adminApi, (await nodeOf(adminApi, t.id, "formation")).id, "forming");
  await openPage(page, `/admin/tournaments/${t.id}/teams/roster`);
  await page.getByRole("link", { name: "Open balancer" }).click();
  await expect(page).toHaveURL(new RegExp(`/balancer\\?tournament=${t.id}`), { timeout: 240_000 });
  const players = page.getByRole("list", { name: "Pool players" });
  for (const reg of pool) {
    await expect(players.getByRole("button", { name: `Select ${reg.primary_handle}` })).toBeVisible();
  }
  await page.getByRole("banner").getByRole("button", { name: "Run balance" }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click({ timeout: 120_000 });
  await expect(page.getByRole("button", { name: "Saved", exact: true })).toBeVisible();
  expect(await adminApi.get(`/api/v1/balancer/tournaments/${t.id}/balance`), "Save persisted the balance").not.toBeNull();
  await page.getByRole("button", { name: "Export to tournament" }).click();
  await expect.poll(async () => (await listTeams(adminApi, t.id)).length, { message: "Export to tournament created the teams" }).toBe(2);
  await openPage(page, `/admin/tournaments/${t.id}/teams/roster`);
  for (const team of await listTeams(adminApi, t.id)) {
    await expect(page.getByRole("row", { name: new RegExp(`^${escapeRe(team.name)}`) })).toBeVisible();
  }
});

test("pickup mix board: Balance teams balances the lineup; Create mix asks for community and game", async ({ adminApi, page }) => {
  const ws = await createWorkspace(adminApi);
  const members = await seedMembers(adminApi, ws.id, 10);
  const mix = await createMix(adminApi, ws.id, members.map((m) => m.member_id));
  await openPage(page, `/balancer/mix/${mix.id}`);
  await expect(page.getByRole("heading", { name: "Lineup" })).toBeVisible();
  await expect(page.getByRole("region", { name: "In the pool" }).getByRole("listitem").or(page.getByRole("region", { name: "In the pool" }).getByRole("button", { name: /^Mx/ }))).toHaveCount(10);
  await page.getByRole("button", { name: "Balance teams" }).click();
  await expect
    .poll(async () => (await adminApi.get<Mix>(`/api/v1/balancer/custom-games/${mix.id}`)).status, { message: "the board's Balance teams balances the mix" })
    .toBe("balanced");

  // Create mix: pick the community, name it, land on the new board.
  await openPage(page, "/balancer/mix");
  await page.getByRole("button", { name: "Create mix" }).click();
  const dialog = page.getByRole("dialog", { name: "Create mix" });
  await dialog.getByRole("combobox", { name: "Community" }).click();
  await page.getByRole("option", { name: ws.name }).click();
  await dialog.getByRole("textbox", { name: "Name" }).fill("Dialog mix");
  await dialog.getByRole("button", { name: "Create mix" }).click();
  await expect(page).toHaveURL(/\/balancer\/mix\/\d+/, { timeout: 240_000 });
  const created = Number(/\/balancer\/mix\/(\d+)/.exec(page.url())![1]);
  expect(await adminApi.get<Mix>(`/api/v1/balancer/custom-games/${created}`)).toMatchObject({ workspace_id: ws.id, name: "Dialog mix" });
});

test("admin rank overview shows a member's canon rank in the selected workspace", async ({ adminApi, page }) => {
  const ws = await createWorkspace(adminApi);
  const [member] = await seedMembers(adminApi, ws.id, 1);
  // The admin's working workspace is a cookie; pin it to this spec's own.
  await page.context().addCookies([{ name: "owt-workspace-id", value: String(ws.id), domain: new URL(BASE_URL).hostname, path: "/" }]);
  await openPage(page, "/admin/ranks");
  await expect(page.getByRole("heading", { name: "Ranks", level: 1 })).toBeVisible();
  for (const column of ["Layer", "Rank", "Δ canon"]) {
    await expect(page.getByRole("columnheader", { name: new RegExp(`^${escapeRe(column)}`) })).toBeVisible();
  }
  // seedMembers gives member 0 a canon tank rank of 2000.
  await expect(page.getByRole("row", { name: new RegExp(`^${escapeRe(member.identity!.handle)} Canon .*Tank 2000`) })).toBeVisible();
  await expect(page.getByRole("button", { name: "Recalculate hidden ratings" })).toBeVisible();
});
